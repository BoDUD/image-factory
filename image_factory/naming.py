"""Restricted filename templates, never Python expressions or filesystem paths."""
from pathlib import PurePosixPath
from string import Formatter
from .data import safe_name

TOKENS={'customer','template','row_id','date','index'}


def output_name(pattern,values,template,index,date,group='none'):
    tokens={'customer':values.get('customer') or values.get('__name') or 'customer',
            'template':template or 'image','row_id':values.get('__index') or f'{index:04d}',
            'index':f'{index:04d}','date':date}
    if not pattern.strip():raise ValueError('命名规则不能为空')
    try:
        for literal,field,spec,conversion in Formatter().parse(pattern):
            if field is not None and (field not in TOKENS or spec or conversion):
                raise ValueError('命名仅支持 {customer} {template} {row_id} {date} {index}')
        name=safe_name(pattern.format_map(tokens))
    except (KeyError,ValueError) as e:
        raise ValueError('命名规则无效：'+str(e)) from e
    if group not in {'none','customer','template'}:raise ValueError('分类方式无效')
    if group=='none':return name
    folder=safe_name(tokens[group])
    if folder.startswith('.'):folder='_'+folder
    return str(PurePosixPath(folder)/name)
