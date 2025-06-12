def resolve_number_with_unit(val: str):
    v = (''.join([x for x in val if x.isdigit() or x in ['.', '-']]))
    try:
        return float(v)
    except:
        return val
