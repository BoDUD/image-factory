import json
import math
from pathlib import Path
from PIL import Image, ImageOps, ImageDraw, ImageFont, ImageFilter, ImageChops

MAX_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def size_ok(width, height):
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise ValueError("尺寸无效或超过 4000 万像素")


def load_image(path):
    with Image.open(path) as im:
        if getattr(im, "n_frames", 1) > 1:
            raise ValueError("检测到动态图，请使用动态贴膜工具，不能静默导出首帧")
        size_ok(*im.size)
        return ImageOps.exif_transpose(im).convert("RGBA")


def font_path():
    candidates = [Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    return next((str(p) for p in candidates if p.exists()), None)


def load_font(path, size):
    path = path or font_path()
    if not path or not Path(path).is_file():
        raise ValueError("字体文件不存在，请指定已安装的字体")
    return ImageFont.truetype(str(path), int(size))


def inspect_template(path):
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    if spec.get("version") != 1:
        raise ValueError("只支持 version=1 的图片模板")
    size_ok(*spec["size"])
    fields = [x["field"] for x in spec.get("text", []) + spec.get("slots", [])]
    if not fields or any(not str(f).strip() for f in fields):
        raise ValueError("模板至少需要一个字段")
    return list(dict.fromkeys(fields))


def asset(template, name):
    path = Path(name)
    return path if path.is_absolute() else Path(template).parent / path


def dependencies(template):
    spec = json.loads(Path(template).read_text(encoding="utf-8"))
    paths = [Path(template)]
    for key in ("background_image", "frame"):
        if spec.get(key):
            paths.append(asset(template, spec[key]))
    for item in spec.get("text", []):
        paths.append(asset(template, item["font"]) if item.get("font") else Path(font_path() or "missing-font"))
    return paths


def render_template(template, values):
    inspect_template(template)
    spec = json.loads(Path(template).read_text(encoding="utf-8"))
    canvas = Image.new("RGBA", tuple(spec["size"]), spec.get("background", "white"))
    if spec.get("background_image"):
        canvas.alpha_composite(ImageOps.fit(load_image(asset(template, spec["background_image"])), canvas.size))
    for slot in spec.get("slots", []):
        x, y, w, h = map(int, slot["box"])
        size_ok(w, h)
        im = ImageOps.fit(load_image(values[slot["field"]]), (w, h), centering=tuple(slot.get("centering", [.5, .5])))
        canvas.alpha_composite(im, (x, y))
    for item in spec.get("text", []):
        text = str(values[item["field"]])
        x, y, w, h = map(int, item["box"])
        size = int(item.get("size", 64)); minimum = int(item.get("min_size", 16))
        fpath = asset(template, item["font"]) if item.get("font") else None
        draw = ImageDraw.Draw(canvas)
        stroke = int(item.get("stroke_width", 0))
        while size >= minimum:
            font = load_font(fpath, size)
            box = draw.multiline_textbbox((0, 0), text, font=font, stroke_width=stroke)
            if box[2] - box[0] <= w and box[3] - box[1] <= h:
                break
            size -= 1
        else:
            raise ValueError(f"字段 {item['field']} 的文字超出模板范围")
        left = x + ((w - (box[2] - box[0])) / 2 if item.get("align") == "center" else 0)
        draw.multiline_text((left - box[0], y - box[1]), text, font=font, fill=item.get("color", "black"), stroke_width=stroke, stroke_fill=item.get("stroke_color", "white"))
    if spec.get("frame"):
        canvas.alpha_composite(load_image(asset(template, spec["frame"])).resize(canvas.size))
    return canvas


def watermark(base, overlay, scale=.3, opacity=.65, position="bottom-right", tile=False, gap=30, blend="normal", feather=0):
    if not 0 < scale <= 2 or not 0 <= opacity <= 1 or gap < 0:
        raise ValueError("水印比例、透明度或间距无效")
    width = max(1, int(base.width * scale)); height = max(1, round(overlay.height * width / overlay.width))
    size_ok(width, height)
    mark = overlay.resize((width, height), Image.Resampling.LANCZOS)
    alpha = mark.getchannel("A")
    if feather:
        alpha = alpha.filter(ImageFilter.GaussianBlur(feather))
    mark.putalpha(alpha.point(lambda a: round(a * opacity)))
    layer = Image.new("RGBA", base.size)
    if tile:
        for y in range(0, base.height, height + gap):
            for x in range(0, base.width, width + gap):
                layer.alpha_composite(mark, (x, y))
    else:
        points = {"center": ((base.width-width)//2, (base.height-height)//2), "top-left": (gap, gap), "bottom-right": (base.width-width-gap, base.height-height-gap)}
        layer.alpha_composite(mark, points[position])
    if blend != "normal":
        operations = {"multiply": ImageChops.multiply, "screen": ImageChops.screen, "overlay": ImageChops.overlay}
        if blend not in operations:
            raise ValueError("不支持此混合模式")
        rgb = operations[blend](base.convert("RGB"), layer.convert("RGB")).convert("RGBA")
        rgb.putalpha(layer.getchannel("A")); layer = rgb
    return Image.alpha_composite(base, layer)


def transform(im, operation, amount=512):
    if operation == "mirror": return ImageOps.mirror(im)
    if operation == "flip": return ImageOps.flip(im)
    if operation == "blur": return im.filter(ImageFilter.GaussianBlur(max(0, min(amount, 100))))
    if operation == "mosaic":
        n = max(1, int(amount)); return im.resize((max(1, im.width//n), max(1, im.height//n))).resize(im.size, Image.Resampling.NEAREST)
    if operation == "square": return ImageOps.fit(im, (min(im.size), min(im.size)))
    if operation == "resize":
        w = int(amount); h = max(1, round(im.height*w/im.width)); size_ok(w,h)
        return im.resize((w,h), Image.Resampling.LANCZOS)
    raise ValueError("未知工具")


def collage(images, columns=3, cell=400, gap=16, background="white"):
    if not images or columns < 1 or cell < 1 or gap < 0:
        raise ValueError("拼图参数无效")
    rows = math.ceil(len(images)/columns)
    size = (columns*cell+(columns+1)*gap, rows*cell+(rows+1)*gap); size_ok(*size)
    result = Image.new("RGBA", size, background)
    for i, im in enumerate(images):
        result.alpha_composite(ImageOps.fit(im, (cell,cell)), (gap+(i%columns)*(cell+gap), gap+(i//columns)*(cell+gap)))
    return result


def save_image(im, path, format="png", background="white"):
    if format == "jpg":
        base = Image.new("RGB", im.size, background); base.paste(im, mask=im.getchannel("A")); base.save(path, "JPEG", quality=95)
    else:
        im.save(path, "PNG")
