"""Authenticated administrator-only content operations; no public answer route."""
import json
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from typing import Literal
from deeptutor.education.application import content_catalog as content


class Review(BaseModel):
    revision: str = Field(min_length=64,max_length=64)
    decision: Literal['publish','retire']
    note: str = Field(min_length=12,max_length=4000)


def register(app, *, connect, judge_available=False):
    def admin(request):
        actor=getattr(request.state,'education_account',None)
        if actor is None: raise HTTPException(401,'Administrator sign-in required')
        if actor.role != 'admin': raise HTTPException(403,'Administrator access required')
        return actor.user_id

    async def package(request):
        data=bytearray()
        async for part in request.stream():
            data.extend(part)
            if len(data)>4*1024*1024: raise HTTPException(413,'Content package exceeds 4 MiB')
        try: return json.loads(data)
        except (ValueError,UnicodeDecodeError): raise HTTPException(400,'Invalid JSON package') from None

    @app.get('/api/edu/content-admin/catalog')
    def catalog(request:Request):
        admin(request); conn=connect()
        try: return content.catalog(conn,judge_available)
        finally: conn.close()

    @app.get('/api/edu/content-admin/starter')
    def starter(request:Request, course_version_id:str):
        admin(request)
        from deeptutor.education.application.number_structure_pack import package
        return package(course_version_id)

    @app.get('/api/edu/content-admin/courses/{version}/items')
    def items(version:str, request:Request, page:int=0):
        admin(request)
        if not 0<=page<=10000: raise HTTPException(400,'Invalid page')
        conn=connect()
        try: return content.items(conn,version,page=page)
        finally: conn.close()

    @app.post('/api/edu/content-admin/import/preview')
    async def preview(request:Request):
        admin(request); body=await package(request); conn=connect()
        try: return content.plan_import(conn,body)[0]
        finally: conn.close()

    @app.post('/api/edu/content-admin/import')
    async def ingest(request:Request):
        actor=admin(request); body=await package(request); conn=connect()
        try: return content.import_package(conn,body,actor)
        finally: conn.close()

    @app.post('/api/edu/content-admin/items/{item_id}/review')
    def review(item_id:str, body:Review, request:Request):
        actor=admin(request); conn=connect()
        try: return content.review_item(conn,item_id,expected_revision=body.revision,decision=body.decision,note=body.note,actor=actor)
        finally: conn.close()
