"""Cross-library retrieval uses live family grants, never a model-selected scope."""
import asyncio
import json

from fastapi import HTTPException
import pytest

from deeptutor.multi_user import knowledge_access, teaching_materials, teaching_policy
from deeptutor.multi_user import teaching_identity as store
from deeptutor.multi_user import teaching_retrieval as retrieval
from deeptutor.multi_user.teaching_grants import Access
from deeptutor.tools.builtin import RAGTool


@pytest.fixture
def family(mu_isolated_root, as_user):
    names = ('admin', 'parent_a', 'parent_b', 'student_a', 'student_b')
    users = {name: {'id': 'u_' + name, 'hash': 'synthetic', 'role': 'user'} for name in names}
    mapping = {name: {'role': 'admin' if name == 'admin' else 'parent' if name.startswith('parent') else 'student'} for name in names}
    for suffix in ('a', 'b'):
        mapping['student_' + suffix]['parent_username'] = 'parent_' + suffix
    store.migrate(users, mapping, apply=True)
    grant = Access(knowledge_bases=['admin:kb:main'], features=['chat'])
    with store.connect(write=True) as conn:
        conn.execute('INSERT INTO teaching_grants VALUES(?,?,?)', ('u_parent_a', grant.model_dump_json(), 'u_admin'))
    with as_user('u_admin', role='admin'):
        for name in ('main', 'unassigned'):
            knowledge_access.admin_kb_manager().update_kb_status(name, 'ready')
    for suffix in ('a', 'b'):
        with as_user('u_parent_' + suffix, role='parent'):
            knowledge_access.current_kb_manager().update_kb_status('family', 'ready')
    return ['admin:kb:main', 'family:u_parent_a:kb:family']


def result(text, title='lesson.md'):
    source = {'title': title, 'source': title, 'page': '3', 'content': text[:200]}
    return {'content': text, 'sources': [source], 'passages': [{'text': text, 'sources': [source]}]}


@pytest.mark.asyncio
async def test_one_query_searches_all_authorized_sources_and_keeps_citations(family, as_user, monkeypatch):
    calls = []
    async def search(query, kb_name, **kwargs):
        calls.append(kb_name)
        return result('Factors of 72: ' + kb_name, kb_name + '.md')
    monkeypatch.setattr('deeptutor.tools.rag_tool.rag_search', search)
    with as_user('u_student_a', role='student'):
        tool = RAGTool()
        assert [p.name for p in tool.get_definition().parameters] == ['query']
        assert 'kb_name' not in tool.get_prompt_hints().input_format
        out = await tool.execute(query='72 factors', kb_name='family:u_parent_b:kb:family', kb_base_dir='/untrusted')
    assert sorted(calls) == sorted(family)
    assert out.success and out.metadata['status'] == 'complete'
    assert {s['kb_name'] for s in out.sources} == set(family)
    assert all(s['page'] == '3' for s in out.sources)


@pytest.mark.asyncio
async def test_child_scope_is_applied_before_retrieval(family, as_user, monkeypatch):
    with as_user('u_parent_a', role='parent'):
        teaching_materials.set_scope('u_parent_a', 'family', [], False)
    calls = []
    async def search(query, kb_name, **kwargs):
        calls.append(kb_name)
        return result('Main textbook')
    monkeypatch.setattr('deeptutor.tools.rag_tool.rag_search', search)
    with as_user('u_student_a', role='student'):
        await retrieval.search_authorized_materials('textbook')
    assert calls == ['admin:kb:main']


@pytest.mark.asyncio
async def test_revoked_family_results_are_discarded_after_search(family, as_user, monkeypatch):
    async def search(query, kb_name, **kwargs):
        if kb_name.startswith('family:'):
            with store.connect(write=True) as conn:
                conn.execute('INSERT INTO material_scopes VALUES(?,?,?,0)', ('u_parent_a', 'family', '[]'))
            return result('REVOKED private passage')
        return result('Permitted main passage')
    monkeypatch.setattr('deeptutor.tools.rag_tool.rag_search', search)
    with as_user('u_student_a', role='student'):
        out = await retrieval.search_authorized_materials('passage')
    assert 'REVOKED' not in json.dumps(out)
    assert out['searched'] == ['admin:kb:main']


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['exception', 'timeout', 'index_error', 'missing_index'])
async def test_partial_failure_is_visible_without_exposing_error_secrets(family, as_user, monkeypatch, failure):
    async def search(query, kb_name, **kwargs):
        if kb_name.startswith('family:'):
            if failure == 'exception':
                raise RuntimeError('sensitive-provider-detail')
            if failure == 'timeout':
                raise TimeoutError('sensitive-provider-detail')
            return {'error': 'sensitive-provider-detail'} if failure == 'index_error' else {'needs_reindex': True}
        return result('Successful source')
    monkeypatch.setattr('deeptutor.tools.rag_tool.rag_search', search)
    with as_user('u_student_a', role='student'):
        out = await RAGTool().execute(query='source')
    assert out.success and out.metadata['status'] == 'partial'
    assert 'incomplete' in out.content and 'Successful source' in out.content
    assert 'sensitive-provider-detail' not in json.dumps(out.metadata)
    assert {s['kb_name'] for s in out.sources} == {'admin:kb:main'}


@pytest.mark.asyncio
async def test_total_failure_has_no_fake_sources(family, as_user, monkeypatch):
    async def search(**kwargs): return {'error_type': 'unavailable'}
    monkeypatch.setattr('deeptutor.tools.rag_tool.rag_search', search)
    with as_user('u_student_a', role='student'):
        out = await RAGTool().execute(query='source')
    assert not out.success and out.sources == []
    assert out.metadata['status'] == 'failed'


@pytest.mark.asyncio
async def test_provider_warning_does_not_become_clean_success(family, as_user, monkeypatch):
    async def search(**kwargs): return {**result('Grounded material'), 'warning': 'Embedding configuration changed'}
    monkeypatch.setattr('deeptutor.tools.rag_tool.rag_search', search)
    with as_user('u_student_a', role='student'):
        out = await retrieval.search_authorized_materials('material')
    assert out['status'] == 'partial' and out['warnings']
    assert 'configuration warning' in out['content']


def test_merge_deduplicates_full_passages_and_retains_each_provenance():
    text = 'A full paragraph about factors. ' * 25
    merged, sources = retrieval._merge('factors', [('main', result(text, 'book.md')), ('family', result(text, 'notes.md'))])
    assert merged.count(text.strip()) == 1
    assert {s['title'] for s in sources} == {'book.md', 'notes.md'}
    assert {s['kb_name'] for s in sources} == {'main', 'family'}


def test_merge_ranks_query_relevance_without_comparing_provider_scores():
    unrelated = result('The water cycle', 'science.md')
    related = result('Factors of 72 and rectangle perimeter', 'math.md')
    unrelated['sources'][0]['score'] = 9999
    related['sources'][0]['score'] = .001
    text, sources = retrieval._merge('72 factors rectangle', [('science', unrelated), ('math', related)])
    assert text.index('Factors of 72') < text.index('The water cycle')
    assert sources[0]['title'] == 'math.md'


@pytest.mark.asyncio
async def test_search_concurrency_is_bounded(family, as_user, monkeypatch):
    active, peak = 0, 0
    async def search(**kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.01)
        active -= 1
        return result('shared content')
    monkeypatch.setattr('deeptutor.tools.rag_tool.rag_search', search)
    monkeypatch.setattr(retrieval, 'SEARCH_CONCURRENCY', 1)
    with as_user('u_student_a', role='student'):
        await retrieval.search_authorized_materials('content')
    assert peak == 1


def test_parent_and_legacy_tool_contract_stay_explicit(family, as_user):
    with as_user('u_parent_a', role='parent'):
        assert 'kb_name' in [p.name for p in RAGTool().get_definition().parameters]


@pytest.mark.asyncio
async def test_family_index_provider_is_selected_on_the_server(family, as_user, monkeypatch):
    from starlette.background import BackgroundTasks
    # This policy-boundary test does not need an installed runtime config.
    monkeypatch.setattr('deeptutor.services.config.load_config_with_main', lambda *a, **kw: {})
    from deeptutor.api.routers import knowledge
    selected = []
    def capture(provider):
        selected.append(provider)
        raise HTTPException(418, 'Stop before creating any files')
    monkeypatch.setattr(knowledge, '_validate_registered_provider', capture)
    with as_user('u_parent_a', role='parent'):
        with pytest.raises(HTTPException) as error:
            await knowledge.create_knowledge_base(BackgroundTasks(), 'new-family', [], 'untrusted-engine', None)
    assert error.value.status_code == 418 and selected == ['llamaindex']


def test_existing_explicit_index_policy_is_preserved(family):
    with store.connect(write=True) as conn:
        conn.execute('INSERT INTO teaching_policy VALUES(1,?,1)', (teaching_policy.TeachingPolicy(material_engine='graphrag').model_dump_json(),))
    assert teaching_policy.material_index_provider() == 'graphrag'


@pytest.mark.asyncio
async def test_chat_pre_retrieval_runs_once_for_all_libraries(family, as_user, monkeypatch):
    from types import SimpleNamespace

    from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
    pipeline = object.__new__(AgenticChatPipeline)
    calls = []
    async def seed(name, query, stream):
        calls.append((name, query))
        return 'Retrieved merged evidence', []
    monkeypatch.setattr(pipeline, '_capability_owned_kbs', lambda _: set())
    monkeypatch.setattr(pipeline, '_selected_kbs', lambda _: family)
    monkeypatch.setattr(pipeline, '_seed_search_one_kb', seed)
    monkeypatch.setattr(pipeline, '_t', lambda *a, **kw: kw['default'])
    with as_user('u_student_a', role='student'):
        text = await pipeline._retrieve_kb_seed_block(SimpleNamespace(user_message='72 factors'), None)
    assert len(calls) == 1 and 'Retrieved merged evidence' in text


@pytest.mark.asyncio
async def test_failed_pre_retrieval_is_reported_to_teacher(family, as_user, monkeypatch):
    from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
    pipeline = object.__new__(AgenticChatPipeline)
    calls = []
    async def execute(name, arguments, **kwargs):
        calls.append(arguments)
        return {'success': False, 'metadata': {'content': 'Retrieval is incomplete', 'status': 'failed'}}
    monkeypatch.setattr(pipeline, '_execute_tool_call', execute)
    monkeypatch.setattr(pipeline, '_t', lambda *a, **kw: kw['default'])
    with as_user('u_student_a', role='student'):
        text, sources = await pipeline._seed_search_one_kb('unused', '72 factors', None)
    assert calls == [{'query': '72 factors'}]
    assert 'incomplete' in text and sources == []
