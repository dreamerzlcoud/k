"""A clearly labeled example document; never uses synthetic samples as a user's handwriting."""
import pymupdf as fitz

from .models import Block, Layout
from .service import import_pdf, save_layout


def create_demo():
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.insert_text((48, 47), "INKLAB  /  ENGINEERING MATHEMATICS", fontsize=10, color=(.28,.38,.32))
        page.insert_text((48, 86), "Worked example sheet", fontsize=25, color=(.15,.22,.18))
        page.insert_text((48, 111), "Sample document - use your own PDF for an assignment.", fontsize=10, color=(.5,.54,.48))
        page.draw_line((48, 131), (547, 131), color=(.82,.86,.8))
        for y, title, prompt in [
            (160, "01   Definite integral", "Evaluate the integral of x squared from 0 to 1."),
            (345, "02   Linear algebra", "Multiply the matrix [[1, 2], [3, 4]] by the vector [x, y]."),
            (555, "03   First-order differential equation", "Solve dy/dt + 2y = 0 with y(0) = 3."),
        ]:
            page.insert_text((48, y), title, fontsize=13, color=(.2,.3,.24))
            page.insert_text((48, y+23), prompt, fontsize=10, color=(.4,.45,.4))
        page.insert_text((48, 809), "Demo solutions are editable. No personal handwriting samples are preloaded.", fontsize=8, color=(.55,.6,.52))
        info = import_pdf(doc.tobytes(), "InkLab - Engineering example.pdf")
    save_layout(Layout(document_id=info["id"], blocks=[
        Block(content=r"\int_0^1 x^2\,dx=\left[\frac{x^3}{3}\right]_0^1=\frac{1}{3}", x=63, y=215, width=465, height=95, size=20),
        Block(content=r"\begin{bmatrix}1&2\\3&4\end{bmatrix}\begin{bmatrix}x\\y\end{bmatrix}=\begin{bmatrix}x+2y\\3x+4y\end{bmatrix}", x=63, y=402, width=465, height=100, size=20),
        Block(content=r"\begin{aligned}\frac{dy}{dt}&=-2y\\y(t)&=Ce^{-2t}\\y(0)=3\quad&\Rightarrow\quad y(t)=3e^{-2t}\end{aligned}", x=63, y=610, width=465, height=155, size=18),
    ]))
    return info
