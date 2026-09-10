"""Animated GIF watermarking with duration preservation and bounded resources."""
import os
import uuid
from pathlib import Path
from PIL import Image
from .imaging import watermark, load_image, size_ok


def watermark_gif(source, overlay, destination, options, cancelled=lambda:False, progress=lambda *a:None, hold_frame=None, hold_ms=0):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if destination in {source,Path(overlay).resolve()}:
        raise ValueError('输出不能覆盖源 GIF 或水印')
    mark=load_image(overlay);frames=[];durations=[]
    with Image.open(source) as gif:
        if gif.format!='GIF':raise ValueError('此工具只处理 GIF')
        count=getattr(gif,'n_frames',1);size_ok(*gif.size)
        if count>500 or gif.width*gif.height*count>80_000_000:
            raise ValueError('超过 500 帧或 8000 万累计像素，请缩小素材后处理')
        if hold_frame is not None and not 0<=hold_frame<count:
            raise ValueError('停留帧超出动画帧数')
        loop=gif.info.get('loop')
        for index in range(count):
            if cancelled():raise ValueError('任务已取消，未提交动画成品')
            gif.seek(index)  # Pillow reconstructs disposal/composited frames sequentially.
            rgba=watermark(gif.convert('RGBA'),mark,**options)
            # Reserve palette index 255 for GIF binary transparency.
            palette=rgba.convert('RGB').quantize(colors=255,method=Image.Quantize.MEDIANCUT)
            alpha=rgba.getchannel('A').point(lambda a:255 if a<128 else 0)
            palette.paste(255,mask=alpha);palette.info['transparency']=255
            frames.append(palette)
            duration=max(10,int(gif.info.get('duration',100)))
            durations.append(duration+(max(0,int(hold_ms)) if index==hold_frame else 0))
            progress(index+1,count)
    temp=destination.with_name('.'+uuid.uuid4().hex+'.gif')
    try:
        kwargs={} if loop is None else {'loop':loop}
        frames[0].save(temp,format='GIF',save_all=True,append_images=frames[1:],duration=durations,transparency=255,disposal=2,optimize=False,**kwargs)
        with Image.open(temp) as check:
            actual=0
            for i in range(check.n_frames):check.seek(i);check.load();actual+=check.info.get('duration',0)
            # GIF durations are quantized to hundredths of a second.
            expected=sum((d//10)*10 for d in durations)
            if actual!=expected:raise ValueError('GIF 时间校验失败')
        os.replace(temp,destination)
    finally:
        if temp.exists():temp.unlink()
    return str(destination)
