"""Closed-form checks of explicit stock question premises, not teaching approval.

Unsupported grammar, missing assets, ties or unknown symbols remain held. The
answer field is compared only after deriving a result from the question/options.
No file/network access, model calls, or biological-context certification.
"""
from fractions import Fraction
import re

# Only ordinary, explicitly supported symbols used in this stock comparison.
ELEMENTS = set('H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og'.split())
NUMBER = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'

def _unique(values):
    if len(values) != 1:
        raise ValueError('Result is not uniquely determined')
    return values[0]

def speed(row):
    match = re.fullmatch(r'Compare the motion of (two|three) ([^.\n]+)\. Which ([^?\n]+?) was moving at (a lower|a higher|the lowest|the highest) speed\?', row['prompt'])
    if not match:
        raise ValueError('Unsupported speed question')
    options = row['options']
    if len(options) != (2 if match[1] == 'two' else 3):
        raise ValueError('Option population differs from premise')
    pattern = rf'(a[n]? .+?) (?:that|who) moved ({NUMBER})\s*(kilometers|miles)(?: (?:north|south|east|west))? in ({NUMBER})\s*(hours?)'
    parsed = [re.fullmatch(pattern, option) for option in options]
    if not all(parsed) or len({x[1] for x in parsed}) != 1 or len({x[3] for x in parsed}) != 1:
        raise ValueError('Unsupported object or mixed distance units')
    rates = []
    for item in parsed:
        distance, time = (Fraction(item[n].replace(',', '')) for n in (2, 4))
        if time <= 0 or distance < 0:
            raise ValueError('Invalid distance or duration')
        rates.append(distance / time)
    extreme = (max if match[4] in ('a higher', 'the highest') else min)(rates)
    index = _unique([i for i, rate in enumerate(rates) if rate == extreme])
    return {'answer': options[index], 'rates': [str(v) for v in rates], 'unit': parsed[0][3] + '/hour', 'method': 'exact_distance_divided_by_time'}

def formula_elements(formula):
    tokens = re.findall(r'([A-Z][a-z]?)([1-9][0-9]*)?', formula)
    if not tokens or ''.join(symbol + count for symbol, count in tokens) != formula or any(symbol not in ELEMENTS for symbol, _ in tokens):
        raise ValueError('Unsupported chemical formula')
    return sorted({symbol for symbol, _ in tokens})

def formula(row):
    if row['prompt'] == 'Select the elementary substance.':
        matches = [re.fullmatch(r'[^()\n]+ \(([A-Za-z0-9]+)\)', option) for option in row['options']]
        if not matches:
            raise ValueError('No options')
        if not all(matches):
            raise ValueError('Unsupported formula option')
        symbols = [formula_elements(m[1]) for m in matches]
        index = _unique([i for i, elements in enumerate(symbols) if len(elements) == 1])
        return {'answer': row['options'][index], 'elements_by_option': symbols, 'method': 'distinct_element_symbols'}
    matches = list(re.finditer(r'The chemical formula for ([^.\n]+?) is ([A-Za-z0-9]+)\.', row['prompt']))
    statement = re.search(r'\n\nComplete the statement\.\n([^.\n]+) is \(\)\.$', row['prompt'])
    if len(matches) != 1 or not statement or statement[1].casefold() != matches[0][1].casefold() or set(row['options']) != {'a compound', 'an elementary substance'} or len(row['options']) != 2:
        raise ValueError('Unsupported formula question')
    symbols = formula_elements(matches[0][2])
    return {'answer': 'an elementary substance' if len(symbols) == 1 else 'a compound', 'elements': symbols, 'formula': matches[0][2], 'method': 'distinct_element_symbols'}

def genotype_phenotype(row):
    prompt = row['prompt']
    question = re.fullmatch(r'Based on this information, what is (?P<subject>[^?\n]+)\x27s (genotype|phenotype) for the (?P<trait>[^?\n]+) (gene|trait)\?', prompt.split('\n\n')[-1])
    if not question:
        raise ValueError('Unsupported genetics question')
    if re.search(r'\bhumans?\b|syndrome|disease|disorder', prompt, re.I):
        raise ValueError('Human medical context requires separate factual review')
    dominance = list(re.finditer(r'The allele for ([^.\n]+?) \(([A-Za-z])\) is (dominant over|recessive to) the allele for ([^.\n]+?) \(([A-Za-z])\)\.', prompt))
    if dominance:
        m = _unique(dominance)
        first, second = m[2], m[5]
        if first.lower() != second.lower() or first == second:
            raise ValueError('Not a two-allele toy model')
        dominant, recessive = (first, second) if m[3] == 'dominant over' else (second, first)
        traits = {first: m[1], second: m[4]}
        genotypes = re.findall(r'([^.\n]+) has the (homozygous|heterozygous) genotype ([A-Za-z]{2}) for the ([^.\n]+) gene\.', prompt[m.end():])
        subject, zygosity, genes, trait = _unique(genotypes)
        _same_subject(question['subject'], subject.strip())
        if trait != question['trait'] or (genes[0] == genes[1]) != (zygosity == 'homozygous'):
            raise ValueError('Conflicting trait or zygosity')
        if any(g not in traits for g in genes):
            raise ValueError('Unknown allele')
        result = traits[dominant if dominant in genes else recessive]
        if question[2] != 'phenotype':
            raise ValueError('Unsupported dominance question')
        return {'answer': result, 'genotype': genes, 'dominant': dominant, 'method': 'explicit_two_allele_dominance_premise'}
    declarations = list(re.finditer(r'The allele ([A-Za-z]) is for ([^.\n]+), and the allele ([A-Za-z]) is for ([^.\n]+)\.', prompt))
    m = _unique(declarations)
    if m[1].lower() != m[3].lower() or m[1] == m[3] or m[2] == m[4]:
        raise ValueError('Not a two-allele toy model')
    traits = {m[2]: m[1], m[4]: m[3]}
    body = prompt[m.end():prompt.rfind('\n\n')].strip()
    individual = re.fullmatch(r'([^.\n]+) has ([^.\n]+)\. ([^.\n]+) has ([^.\n]+)\.', body)
    if not individual or individual[2] not in traits:
        raise ValueError('Individual phenotype or allele statement missing')
    _same_subject(question['subject'], individual[1].rstrip(',').split(',')[0])
    _same_subject(question['subject'], individual[3])
    two = re.fullmatch(r'two alleles for (.+)', individual[4])
    one = re.fullmatch(r'one allele for (.+) and one allele for (.+)', individual[4])
    if two and two[1] in traits:
        genes = traits[two[1]] * 2
    elif one and one[1] in traits and one[2] in traits:
        genes = ''.join(sorted((traits[one[1]], traits[one[2]])))
    else:
        raise ValueError('Unsupported allele counts')
    return {'answer': genes if question[2] == 'genotype' else individual[2], 'genotype': genes, 'phenotype': individual[2], 'method': 'explicit_allele_count_or_stated_phenotype'}

def _same_subject(target, stated):
    if target == stated:
        return
    if target.startswith('this ') and target.split()[-1] in ('plant', 'fish', 'fly'):
        noun = target.split()[-1]
        if stated == 'This ' + noun:
            return
        individual = re.fullmatch(r'A certain ([A-Za-z ]+ ' + noun + r') from this group', stated)
        if individual and target in ('this ' + noun, 'this ' + individual[1]):
            return
    raise ValueError('Individual subject does not match the question')

def verify(row, kind):
    if row.get('issues'):
        raise ValueError('Existing structural hold retained')
    if not row.get('options') or len(row['options']) != len(set(row['options'])):
        raise ValueError('Missing or ambiguous options')
    checker = {'speed': speed, 'formula': formula, 'genetics': genotype_phenotype}[kind]
    result = checker(row)
    if row['options'].count(result['answer']) != 1 or row['answer'] != result['answer']:
        raise ValueError('Source answer mismatch')
    return {**result, 'scope': 'Conditional on explicit question premises; does not certify physical realism, biological or chemical context, grade suitability, or formal Quiz approval.'}
