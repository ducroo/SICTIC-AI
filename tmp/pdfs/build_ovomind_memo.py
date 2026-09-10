from pathlib import Path
import re
from html import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from pypdf import PdfReader

ROOT = Path('/Users/openclaw/SICTIC-AI')
INPUT = ROOT / 'output/ovomind-investment-memo-2026-09-05.md'
OUTPUT = ROOT / 'output/pdf/ovomind-investment-memo-2026-09-05.pdf'
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

regular = Path('/System/Library/Fonts/Supplemental/Arial.ttf')
bold = Path('/System/Library/Fonts/Supplemental/Arial Bold.ttf')
if regular.exists() and bold.exists():
    pdfmetrics.registerFont(TTFont('Memo', str(regular)))
    pdfmetrics.registerFont(TTFont('Memo-Bold', str(bold)))
    pdfmetrics.registerFontFamily('Memo', normal='Memo', bold='Memo-Bold', italic='Memo', boldItalic='Memo-Bold')
    FONT, BOLD = 'Memo', 'Memo-Bold'
else:
    FONT, BOLD = 'Helvetica', 'Helvetica-Bold'

NAVY = colors.HexColor('#14343C')
TEAL = colors.HexColor('#227D82')
INK = colors.HexColor('#172B33')
GRAY = colors.HexColor('#536870')
LINE = colors.HexColor('#D5E0E2')
WIDTH, HEIGHT = A4
MARGIN = 40
CONTENT_WIDTH = WIDTH - 2*MARGIN

styles = {
    'title': ParagraphStyle('title', fontName=BOLD, fontSize=20, leading=23, textColor=NAVY, spaceAfter=7),
    'body': ParagraphStyle('body', fontName=FONT, fontSize=9.3, leading=12.0, textColor=INK, spaceAfter=5),
    'h2': ParagraphStyle('h2', fontName=BOLD, fontSize=11, leading=13.5, textColor=TEAL, spaceBefore=9, spaceAfter=5, keepWithNext=True),
    'cell': ParagraphStyle('cell', fontName=FONT, fontSize=8.25, leading=10.7, textColor=INK),
    'th': ParagraphStyle('th', fontName=BOLD, fontSize=8.1, leading=10.1, textColor=colors.white),
    'small': ParagraphStyle('small', fontName=FONT, fontSize=7.6, leading=9.6, textColor=GRAY, spaceAfter=4),
    'bullet': ParagraphStyle('bullet', fontName=FONT, fontSize=9.3, leading=12.0, textColor=INK, spaceAfter=4, leftIndent=8, firstLineIndent=-8),
}

def inline(s):
    s = s.replace('Aᵢ', 'A_i').replace('A₁', 'A_1').replace('A₂', 'A_2').replace('A₃', 'A_3').replace('A₄', 'A_4')
    s = s.replace('−', '-').replace('×', 'x')
    s = escape(s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    return s

def para(s, style='body'):
    return Paragraph(inline(s), styles[style])

def table(lines):
    rows = [[c.strip() for c in l.strip().strip('|').split('|')] for l in lines]
    rows = [r for r in rows if not all(re.fullmatch(r'[:\- ]+', c) for c in r)]
    n = len(rows[0])
    if n == 6:
        widths = [177, 60, 40, 58, 123, CONTENT_WIDTH - 458]
    elif rows[0][0] == 'Component':
        widths = [65, 205, CONTENT_WIDTH - 270]
    else:
        widths = [148, 186, CONTENT_WIDTH - 334]
    cells = [[para(c, 'th' if i == 0 else 'cell') for c in row] for i,row in enumerate(rows)]
    t = Table(cells, colWidths=widths, hAlign='LEFT', repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),NAVY),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.HexColor('#F1F6F6'),colors.white]),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),6),
        ('RIGHTPADDING',(0,0),(-1,-1),6),
        ('TOPPADDING',(0,0),(-1,-1),5),
        ('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('LINEBELOW',(0,0),(-1,0),0.4,NAVY),
        ('LINEBELOW',(0,1),(-1,-1),0.3,LINE),
    ]))
    return t

text = INPUT.read_text()
lines = text.splitlines()
story = []
i = 0
while i < len(lines):
    line = lines[i].strip()
    if not line:
        i += 1
        continue
    if line == '<!-- PAGE BREAK -->':
        story.append(PageBreak())
        i += 1
        continue
    if line.startswith('## Sources and scope'):
        story.append(Spacer(1,5))
        story.append(para('Sources: [1] Startup profile; [2] Traction; [3] DD checks; [4] DD priorities; [5] Team; [6] SHA review. Company-focused insights updated 4 September 2026; related person profiles cross-checked. Primary documents and external claims not independently verified. Source links and detailed gaps accompany this memo.', 'small'))
        break
    if line.startswith('# '):
        story.append(para(line[2:], 'title'))
        i += 1
        continue
    if line.startswith('## '):
        story.append(para(line[3:], 'h2'))
        i += 1
        continue
    if line.startswith('**5 September'):
        story.append(para(line))
        i += 1
        continue
    if line.startswith('|'):
        block = []
        while i < len(lines) and lines[i].strip().startswith('|'):
            block.append(lines[i])
            i += 1
        story.append(table(block))
        story.append(Spacer(1,4))
        continue
    if line.startswith('- '):
        story.append(para('• '+line[2:], 'bullet'))
        i += 1
        continue
    if re.match(r'^\d+\. ', line):
        story.append(para(line, 'bullet'))
        i += 1
        continue
    block = [line]
    i += 1
    while i < len(lines) and lines[i].strip() and not lines[i].startswith(('#','|','<!--','- ')) and not re.match(r'^\d+\. ', lines[i]):
        block.append(lines[i].strip())
        i += 1
    story.append(para(' '.join(block)))

def page_frame(c, doc):
    c.saveState()
    c.setFont(BOLD, 7.5)
    c.setFillColor(TEAL)
    c.drawString(MARGIN, HEIGHT - 23, 'INVESTMENT ASSESSMENT  /  EXISTING INSIGHTS')
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.line(MARGIN, 31, WIDTH - MARGIN, 31)
    c.setFont(FONT, 7.3)
    c.setFillColor(GRAY)
    c.drawString(MARGIN, 19, 'OVOMIND  |  5 September 2026  |  Evidence gaps are not proof of company deficiencies')
    c.drawRightString(WIDTH - MARGIN, 19, str(doc.page))
    c.restoreState()

doc = SimpleDocTemplate(str(OUTPUT), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                        topMargin=39, bottomMargin=40, title='Ovomind — Investment memo',
                        author='Investment analysis', subject='Combined insights and essential information gaps')
doc.build(story, onFirstPage=page_frame, onLaterPages=page_frame)
reader = PdfReader(str(OUTPUT))
print('Output:', OUTPUT)
print('Pages:', len(reader.pages))
for n,page in enumerate(reader.pages,1):
    t = page.extract_text()
    print('Page', n, 'words:', len(t.split()), 'ending:', t[-180:].replace('\n',' '))
assert len(reader.pages) == 2, 'Memo must be exactly two pages'
