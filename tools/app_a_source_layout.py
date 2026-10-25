"""Read App A's actual split bindings as one logical source for historical audits.

Never loads frozen code as an implementation. Only private file headers are
removed; the moved board initializers' intended external linkage is normalised
back to their former spelling for old source-contract tests. New layout tests
separately verify the real header and separate C build. B is read unchanged.
"""
import argparse
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def app_source_files():
    """Physical App A inputs for new manifests, including the split bodies."""
    return [ROOT/'foc2_app_a/Core/Src/main.c',
        *sorted((ROOT/'foc2_app_a/Core/Src/App').rglob('*.inc')),
        *sorted((ROOT/'foc2_app_a/Core/Src/App').rglob('*.c')),
        *sorted((ROOT/'foc2_app_a/Core/Src/App').rglob('*.h')),
        ROOT/'foc2_app_a/Core/Src/App/layout.json']


def read_app_source(path,*args,**kwargs):
    path=Path(path);text=path.read_text(*args,**kwargs)
    if path.resolve()!=ROOT/'foc2_app_a/Core/Src/main.c':return text
    layout_path=path.parent/'App/layout.json'
    if not layout_path.exists():return text
    m=json.loads(layout_path.read_text())
    for item in m['modules']:
        include='#include "'+item['include']+'"\n'
        if text.count(include)!=1:raise ValueError('App layout include missing/duplicated: '+item['include'])
        body=(ROOT/item['path']).read_text()
        if not body.startswith(item['prefix']):raise ValueError('App module header changed: '+item['path'])
        body=body[len(item['prefix']):]
        text=text.replace(include,body)
    decl='#include "../board/app_board.h"\n'
    if text.count(decl)!=1:raise ValueError('Board header binding missing')
    text=text.replace(decl,m['original_board_prototypes'])
    board=(ROOT/m['board_path']).read_text()
    if not board.startswith(m['board_prefix']):raise ValueError('Board module header changed')
    board=board[len(m['board_prefix']):]
    for name in ('MX_GPIO_Init','MX_TIM1_Init','MX_SPI1_Init','MX_LPUART1_UART_Init','MX_ADC1_Init','MX_ADC2_Init'):
        board=board.replace('void '+name+'(void)','static void '+name+'(void)')
    if text.count(m['board_marker'])!=1:raise ValueError('Board source map marker missing')
    return text.replace(m['board_marker'],board)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('path',type=Path,nargs='?',default=ROOT/'foc2_app_a/Core/Src/main.c')
    print(read_app_source(p.parse_args().path),end='')
