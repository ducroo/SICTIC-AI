import re
from typing import Tuple
from lib.logger import get_logger

logger = get_logger(__name__)


class DecimalOutliner:
    def __init__(self):
        self.idx = []
        self.header_level = 0

    def parse(self, item: str) -> Tuple[bool, str, str]:
        clean_item = item.strip()
        is_header = clean_item.startswith('#')
        
        level = len(clean_item) - len(clean_item.lstrip('#')) if is_header else self.header_level + 1

        if is_header:
            self.header_level = level
            if is_header and level == 1:
                m = re.search(r'\d+', clean_item)
                self.idx = [int(m.group()) if m else 1]
            else:
                self.idx = (self.idx + [0] * level)[:level]
                self.idx[-1] += 1
        else:
            self.idx = (self.idx + [0] * level)[:level]
            self.idx[-1] += 1
            
        idx_string = '.'.join(map(str, self.idx))
        return is_header, clean_item.lstrip('#').strip(), idx_string
