from ASFINT.Push.pushers import *
from ASFINT.Pull.pullers import *
from ASFINT.Transform.Processor import ASUCProcessor
from typing import Callable

PROCESS_TYPES = {
    'ABSA': {
        'pull': pull_csv, 
        'push': push_csv, 
        'process': ASUCProcessor('ABSA'), 
        'naming': {
            'raw tag': "RF", 
            'clean tag': "GF", 
            'clean file name': "ABSA", 
            'raw name dependency': ["Date"],
        }, 
    }, 
    'CONTINGENCY': {
        'pull': pull_txt, 
        'push': push_csv, 
        'process': ASUCProcessor('CONTINGENCY'), 
        'naming': {
            'raw tag': "RF", 
            'clean tag': "GF", 
            'clean file name': "ABSA", 
            'raw name dependency': ["Date"],
        }, 
    }, 
    'OASIS': {
        'pull': pull_csv, 
        'push': push_csv,
        'process': ASUCProcessor('OASIS'),  
        'naming': {
            'raw tag':"RF", 
            'clean tag':"GF", 
            'clean file name':"OASIS", 
            'raw name dependency':["Date"], 
        }
    }, 
    'FR': {
        'pull': pull_fr,
        'push': push_csv,
        'process': ASUCProcessor('FR'),
        'naming': {
            'raw tag':"RF",
            'clean tag':"GF",
            'clean file name':"Ficomm-Reso",
            'date format':"%m-%d-%Y",
            'raw name dependency':["Date", "Numbering", "Coding"],
        }
    },
    'RECONCILE': {
        'pull': pull_reconcile,
        'push': push_csv,
        'process': ASUCProcessor('RECONCILE'),
        'naming': {
            'raw tag': "RF",
            'clean tag': "GF",
            'clean file name': "Reconciled",
            'raw name dependency': ["Date"],
        },
    },
}

def get_pFuncs(process_type: str, func: str) -> Callable: 
    process_type = process_type.strip().upper()
    if process_type in PROCESS_TYPES: 
        fields = PROCESS_TYPES[process_type]
        func = fields.get(func.strip().lower(), None)
        if func is None:
            raise ValueError(f"Inputted function '{func}' not supported, select from: '{fields.keys()}'")
        else:
            return func
    else:
        raise ValueError(f"Inputted process type '{process_type}' not supported, select from: '{list(PROCESS_TYPES.keys())}'")
    
def get_naming(process_type: str, tag: str):
    process_type = process_type.strip().upper()
    if process_type in PROCESS_TYPES: 
        fields = PROCESS_TYPES[process_type]['naming']
        namingConvention = fields.get(tag.strip().lower(), None)
        if namingConvention is None:
             raise ValueError(f"Inputted tag '{tag}' not supported, select from: '{fields.keys()}'")
        else:
            return namingConvention
    else:
        raise ValueError(f"Inputted process type '{process_type}' not supported, select from: '{list(PROCESS_TYPES.keys())}'")