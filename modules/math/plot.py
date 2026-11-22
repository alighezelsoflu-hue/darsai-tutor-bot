import asyncio
import math
import re
from io import BytesIO
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont
from telegram import InputFile, Update
from telegram.ext import CommandHandler, ContextTypes, Application

from .shared import Expression, nice, strip_invisible

MAX_PLOT_POINTS = 900
_FUNCTION_PREFIX = re.compile(r"^\s*(?:y|f\s*\(\s*x\s*\))\s*=\s*", flags=re.I)


def load_font(size: int = 20):
    for path in ["arial.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def parse_plot_input(text: str) -> Tuple[str, float, float]:
    text = strip_invisible(text).strip()
    if not text:
        raise ValueError("Please provide a function, e.g. /plot y=x^2 range -5 5")
    xmin, xmax = -10.0, 10.0
    match = re.search(r"\brange\s+([-+]?\d+(?:\.\d+)?)\s+([-+]?\d+(?:\.\d+)?)", text, flags=re.I)
    if match:
        xmin = float(match.group(1))
        xmax = float(match.group(2))
        text = text[:match.start()] + text[match.end():]
    expr = _FUNCTION_PREFIX.sub("", text).strip()
    if not expr:
        raise ValueError("Please provide a function, e.g. /plot y=x^2 range -5 5")
    if xmax <= xmin:
        raise ValueError("Range end must be greater than range start.")
    if xmax - xmin > 10000:
        raise ValueError("Range is too large.")
    return expr, xmin, xmax


class Mapper:
    def __init__(self, left, top, right, bottom, xmin, xmax, ymin, ymax):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom
        self.xmin, self.xmax, self.ymin, self.ymax = xmin, xmax, ymin, ymax
        self.width, self.height = right - left, bottom - top
    def x(self, value: float) -> int:
        return int(self.left + (value - self.xmin) / (self.xmax - self.xmin) * self.width)
    def y(self, value: float) -> int:
        return int(self.bottom - (value - self.ymin) / (self.ymax - self.ymin) * self.height)


def padded_range(values):
    vals = [v for v in values if math.isfinite(v)]
    if not vals:
        return -1, 1
    lo, hi = min(vals), max(vals)
    if abs(hi - lo) < 1e-12:
        pad = max(1, abs(hi) * 0.1)
        return lo - pad, hi + pad
    pad = (hi - lo) * 0.12
    return lo - pad, hi + pad


def create_plot(expr: str, xmin: float, xmax: float) -> BytesIO:
    width, height = 1200, 780
    left, top, right, bottom = 95, 95, 1140, 660
    f = Expression(expr)
    xs, ys = [], []
    for i in range(MAX_PLOT_POINTS):
        x = xmin + (xmax - xmin) * i / (MAX_PLOT_POINTS - 1)
        xs.append(x)
        try:
            ys.append(f(x))
        except ValueError:
            ys.append(None)
    valid_y = [y for y in ys if y is not None]
    if not valid_y:
        raise ValueError("Could not evaluate the function in this range.")
    ymin, ymax = padded_range(valid_y)
    mapper = Mapper(left, top, right, bottom, xmin, xmax, ymin, ymax)

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(30)
    small_font = load_font(16)
    draw.text((left, 30), f"y = {expr}", fill="black", font=title_font)
    draw.rectangle((left, top, right, bottom), outline="#222222", width=2, fill="#fbfbfb")

    grid = 8
    for i in range(grid + 1):
        gx = left + i * (right - left) / grid
        gy = top + i * (bottom - top) / grid
        draw.line((gx, top, gx, bottom), fill="#dddddd")
        draw.line((left, gy, right, gy), fill="#dddddd")
        xv = xmin + i * (xmax - xmin) / grid
        yv = ymax - i * (ymax - ymin) / grid
        draw.text((gx - 22, bottom + 10), nice(xv, 4), fill="#333333", font=small_font)
        draw.text((12, gy - 8), nice(yv, 4), fill="#333333", font=small_font)
    if xmin <= 0 <= xmax:
        draw.line((mapper.x(0), top, mapper.x(0), bottom), fill="#333333", width=2)
    if ymin <= 0 <= ymax:
        draw.line((left, mapper.y(0), right, mapper.y(0)), fill="#333333", width=2)

    last = None
    for x, y in zip(xs, ys):
        if y is None:
            last = None
            continue
        point = (mapper.x(x), mapper.y(y))
        if last:
            # Avoid huge vertical jumps from asymptotes.
            if abs(point[1] - last[1]) < height:
                draw.line((last[0], last[1], point[0], point[1]), fill="#1f77b4", width=3)
        last = point

    out = BytesIO()
    image.save(out, format="PNG")
    out.seek(0)
    out.name = "plot.png"
    return out


async def plot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        expr, xmin, xmax = parse_plot_input(" ".join(context.args or []))
        image = await asyncio.to_thread(create_plot, expr, xmin, xmax)
    except ValueError as error:
        await update.message.reply_text(
            "Plot error.\n\n"
            f"Error: {error}\n\n"
            "Usage:\n"
            "/plot y=x^2 range -5 5\n"
            "/plot sin(x) range -6.28 6.28"
        )
        return
    await update.message.reply_photo(photo=InputFile(image, filename="plot.png"), caption=f"Plot: y = {expr}")


def register_plot_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("plot", plot_command))
