"""
Generación de documentos DOCX con encabezado institucional.

Endpoint: POST /api/grupos/{grupo_id}/generar-documento
Body   : { "contenido_md": "...", "titulo": "..." }
Returns: archivo .docx descargable

Flujo:
  1. El frontend acumula el Markdown de la respuesta IA en el chat.
  2. Detecta que es un documento (contiene encabezados/listas).
  3. POST a este endpoint con el MD y el título.
  4. El backend convierte MD → DOCX con encabezado institucional.
  5. El browser descarga el archivo.
"""

import io
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_docente
from database import get_db
from models import Docente, Grupo

router = APIRouter(prefix="/api", tags=["documentos"])


# ════════════════════════════════════════════════════════════════
# SCHEMA
# ════════════════════════════════════════════════════════════════

class GenerarDocumentoRequest(BaseModel):
    contenido_md: str
    titulo: str = "Documento"


# ════════════════════════════════════════════════════════════════
# HELPERS DOCX — encabezado institucional estilo Teachy
# ════════════════════════════════════════════════════════════════

def _docx_bytes(md: str, titulo: str, docente: Docente, grupo: Grupo) -> bytes:
    """
    Construye el DOCX completo:
      - Encabezado institucional con marca de la plataforma
      - Cuerpo desde Markdown
      - Pie de página con branding
    """
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    # ── Paleta ──────────────────────────────────────────────────
    AZUL_OSCURO = RGBColor(0x1E, 0x40, 0xAF)   # azul-800 Tailwind
    AZUL_MEDIO  = RGBColor(0x1D, 0x4E, 0xD8)   # azul-700
    AZUL_CLARO  = RGBColor(0x93, 0xC5, 0xFD)   # azul-300
    BLANCO      = RGBColor(0xFF, 0xFF, 0xFF)
    GRIS        = RGBColor(0x6B, 0x72, 0x80)

    HEX_AZUL_OSC = '1E40AF'
    HEX_AZUL_CLR = 'DBEAFE'
    HEX_GRIS_CLR = 'F3F4F6'

    # ── Helpers ─────────────────────────────────────────────────
    def set_cell_bg(cell, hex_color: str):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:val'), 'clear')
        shd.set(qn('w:color'), 'auto')
        shd.set(qn('w:fill'), hex_color)
        tcPr.append(shd)

    def set_cell_border_none(cell):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        tcBorders = OxmlElement('w:tcBorders')
        for side in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
            bd = OxmlElement(f'w:{side}')
            bd.set(qn('w:val'), 'nil')
            tcBorders.append(bd)
        tcPr.append(tcBorders)

    def no_border_table(tbl):
        tbl.style = 'Table Grid'
        for row in tbl.rows:
            for cell in row.cells:
                set_cell_border_none(cell)

    # ── Documento ────────────────────────────────────────────────
    doc = Document()

    # Márgenes
    for section in doc.sections:
        section.top_margin    = Cm(1.5)
        section.bottom_margin = Cm(2)
        section.left_margin   = Cm(2.5)
        section.right_margin  = Cm(2.5)

    # ══════════════════════════════════════════════════════════════
    # FRANJA SUPERIOR — azul sólido con logo/marca
    # ══════════════════════════════════════════════════════════════
    tbl_top = doc.add_table(rows=1, cols=2)
    no_border_table(tbl_top)
    tbl_top.columns[0].width = Cm(10)
    tbl_top.columns[1].width = Cm(8)

    # Celda izquierda: nombre de la plataforma
    cl = tbl_top.cell(0, 0)
    set_cell_bg(cl, HEX_AZUL_OSC)
    pl = cl.paragraphs[0]
    pl.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pl.paragraph_format.left_indent  = Cm(0.4)
    pl.paragraph_format.space_before = Pt(8)
    pl.paragraph_format.space_after  = Pt(8)
    rl = pl.add_run('Asistente Pedagógico IA')
    rl.font.size  = Pt(14)
    rl.font.bold  = True
    rl.font.color.rgb = BLANCO

    # Celda derecha: fecha
    cr = tbl_top.cell(0, 1)
    set_cell_bg(cr, HEX_AZUL_OSC)
    pr = cr.paragraphs[0]
    pr.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    pr.paragraph_format.right_indent = Cm(0.4)
    pr.paragraph_format.space_before = Pt(8)
    pr.paragraph_format.space_after  = Pt(8)
    rr = pr.add_run(f'Generado: {datetime.now().strftime("%d/%m/%Y  %H:%M")}')
    rr.font.size      = Pt(9)
    rr.font.color.rgb = AZUL_CLARO

    # ══════════════════════════════════════════════════════════════
    # TABLA DE METADATOS (2 filas × 2 cols)
    # ══════════════════════════════════════════════════════════════
    tbl_meta = doc.add_table(rows=2, cols=2)
    no_border_table(tbl_meta)

    inst = (getattr(docente, 'institucion', None) or '').strip()
    ciudad = (getattr(docente, 'ciudad', None) or '').strip()
    inst_display = ' — '.join(filter(None, [inst or 'Sin institución', ciudad]))

    meta = [
        [
            ('Docente:', docente.nombre_completo),
            ('Generado por:', 'Asistente Pedagógico IA'),
        ],
        [
            ('Institución:', inst_display),
            ('Grupo:', f'{grupo.nombre_grupo} · {grupo.grado} · {grupo.asignatura} · P{grupo.periodo_actual}'),
        ],
    ]

    for ri, fila in enumerate(meta):
        for ci, (label, valor) in enumerate(fila):
            cell = tbl_meta.cell(ri, ci)
            set_cell_bg(cell, HEX_GRIS_CLR)
            p = cell.paragraphs[0]
            p.paragraph_format.left_indent  = Cm(0.3)
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after  = Pt(4)
            r_label = p.add_run(label + ' ')
            r_label.font.size      = Pt(8)
            r_label.font.bold      = True
            r_label.font.color.rgb = AZUL_MEDIO
            r_val = p.add_run(valor)
            r_val.font.size      = Pt(8)
            r_val.font.color.rgb = GRIS

    # Espacio
    sp = doc.add_paragraph()
    sp.paragraph_format.space_after = Pt(4)

    # ══════════════════════════════════════════════════════════════
    # TÍTULO DEL DOCUMENTO
    # ══════════════════════════════════════════════════════════════
    h_titulo = doc.add_heading(titulo, level=1)
    h_titulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in h_titulo.runs:
        run.font.color.rgb = AZUL_OSCURO
        run.font.size = Pt(18)

    # Línea divisora
    p_div = doc.add_paragraph()
    p_div.paragraph_format.space_before = Pt(0)
    p_div.paragraph_format.space_after  = Pt(12)
    r_div = p_div.add_run('─' * 85)
    r_div.font.color.rgb = AZUL_CLARO
    r_div.font.size = Pt(8)

    # ══════════════════════════════════════════════════════════════
    # CUERPO — Markdown → DOCX
    # ══════════════════════════════════════════════════════════════
    _render_md(doc, md, AZUL_OSCURO)

    # ══════════════════════════════════════════════════════════════
    # PIE — franja de marca
    # ══════════════════════════════════════════════════════════════
    pie_sp = doc.add_paragraph()
    pie_sp.paragraph_format.space_before = Pt(16)
    pie_sp.paragraph_format.space_after  = Pt(0)

    tbl_pie = doc.add_table(rows=1, cols=1)
    no_border_table(tbl_pie)
    cp = tbl_pie.cell(0, 0)
    set_cell_bg(cp, HEX_AZUL_CLR)
    pp = cp.paragraphs[0]
    pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pp.paragraph_format.space_before = Pt(6)
    pp.paragraph_format.space_after  = Pt(6)
    rp = pp.add_run(
        f'Generado con Asistente Pedagógico IA  •  '
        f'{datetime.now().strftime("%d/%m/%Y")}  •  '
        'Documento de uso educativo — No editar el encabezado'
    )
    rp.font.size      = Pt(7)
    rp.font.italic    = True
    rp.font.color.rgb = AZUL_MEDIO

    # ── Serializar ───────────────────────────────────────────────
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def _render_md(doc, md: str, h1_color):
    """
    Parsea Markdown básico y lo escribe en el documento con python-docx.
    Soporta: # encabezados, **negrita**, *itálica*, listas, código, párrafos.
    """
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    AZUL = h1_color

    lines = md.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()

        # ── Bloque de código ````lang ... ``` ────────────────────
        if s.startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            if code_lines:
                p = doc.add_paragraph()
                p.paragraph_format.left_indent  = Pt(20)
                p.paragraph_format.space_before = Pt(4)
                p.paragraph_format.space_after  = Pt(4)
                r = p.add_run('\n'.join(code_lines))
                r.font.name = 'Courier New'
                r.font.size = Pt(9)
                r.font.color.rgb = RGBColor(0x37, 0x41, 0x51)
            i += 1  # saltar cierre ```
            continue

        # ── Encabezados ──────────────────────────────────────────
        m = re.match(r'^(#{1,6})\s+(.+)', s)
        if m:
            level  = min(len(m.group(1)), 4)
            text   = _strip_inline(m.group(2))
            h = doc.add_heading(text, level=level)
            if level == 1:
                for r in h.runs:
                    r.font.color.rgb = AZUL
                    r.font.size = Pt(16)
            elif level == 2:
                for r in h.runs:
                    r.font.color.rgb = AZUL
            i += 1
            continue

        # ── Lista viñetas ────────────────────────────────────────
        m_bul = re.match(r'^[-*+]\s+(.+)', s)
        if m_bul:
            p = doc.add_paragraph(style='List Bullet')
            _inline_runs(p, m_bul.group(1))
            i += 1
            continue

        # ── Lista numerada ───────────────────────────────────────
        m_num = re.match(r'^\d+[.)]\s+(.+)', s)
        if m_num:
            p = doc.add_paragraph(style='List Number')
            _inline_runs(p, m_num.group(1))
            i += 1
            continue

        # ── Línea horizontal ─────────────────────────────────────
        if re.match(r'^[-*_]{3,}$', s):
            p = doc.add_paragraph()
            r = p.add_run('─' * 80)
            r.font.size = Pt(8)
            r.font.color.rgb = RGBColor(0xD1, 0xD5, 0xDB)
            i += 1
            continue

        # ── Línea vacía → espacio ────────────────────────────────
        if not s:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after  = Pt(0)
            i += 1
            continue

        # ── Párrafo normal ───────────────────────────────────────
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        _inline_runs(p, s)
        i += 1


def _strip_inline(text: str) -> str:
    """Quita marcadores MD inline para texto plano."""
    t = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    t = re.sub(r'__(.+?)__', r'\1', t)
    t = re.sub(r'\*(.+?)\*', r'\1', t)
    t = re.sub(r'_(.+?)_', r'\1', t)
    t = re.sub(r'`(.+?)`', r'\1', t)
    t = re.sub(r'~~(.+?)~~', r'\1', t)
    return t


def _inline_runs(paragraph, text: str):
    """
    Agrega runs al párrafo respetando **negrita** e *itálica* inline.
    Tokeniza el texto y produce runs separados con el formato correcto.
    """
    from docx.shared import Pt

    # Tokenizar: separar en segmentos de texto con formato
    tokens = re.split(r'(\*\*.*?\*\*|\*.*?\*|__.*?__|_.*?_|`.*?`)', text)
    for token in tokens:
        if not token:
            continue
        m_bold   = re.match(r'\*\*(.+?)\*\*', token) or re.match(r'__(.+?)__', token)
        m_italic = re.match(r'\*(.+?)\*', token) or re.match(r'_(.+?)_', token)
        m_code   = re.match(r'`(.+?)`', token)
        if m_bold:
            r = paragraph.add_run(m_bold.group(1))
            r.bold = True
        elif m_italic:
            r = paragraph.add_run(m_italic.group(1))
            r.italic = True
        elif m_code:
            r = paragraph.add_run(m_code.group(1))
            r.font.name = 'Courier New'
            r.font.size = Pt(9)
        else:
            paragraph.add_run(token)


# ════════════════════════════════════════════════════════════════
# ENDPOINT
# ════════════════════════════════════════════════════════════════

@router.post("/grupos/{grupo_id}/generar-documento")
async def generar_documento(
    grupo_id: str,
    body: GenerarDocumentoRequest,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    """
    Recibe Markdown de la IA, lo convierte a DOCX con encabezado institucional
    y devuelve el archivo para descarga directa.
    """
    grupo = db.query(Grupo).filter(
        Grupo.id_grupo == grupo_id,
        Grupo.id_docente == docente.id_docente,
    ).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    titulo = (body.titulo or 'Documento').strip()[:120]

    try:
        docx_bytes = _docx_bytes(
            md=body.contenido_md,
            titulo=titulo,
            docente=docente,
            grupo=grupo,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando DOCX: {e}")

    # Nombre de archivo seguro
    safe = re.sub(r'[^\w\s-]', '', titulo).strip().replace(' ', '_')[:60] or 'documento'
    filename = f"{safe}.docx"

    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
