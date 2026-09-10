"""Exercise editor rendering in the frozen executable, without Photoshop."""
from PIL import Image,ImageDraw
from PySide6.QtWidgets import QApplication
from .editor import WatermarkEditor,TemplateLayoutEditor
from . import imaging


def run(root,template):
    values={'customer':'今今','order_id':'A001'}
    base=imaging.render_template(template,values)
    mark=Image.new('RGBA',(320,90),(0,0,0,0));draw=ImageDraw.Draw(mark)
    draw.rounded_rectangle((0,0,319,89),radius=18,fill='#13877e')
    draw.text((22,20),'Image Factory',font=imaging.load_font(None,34),fill='white')
    water=WatermarkEditor(base,mark,{'scale':.35,'opacity':.8})
    water.move_box([100,720,315,89]);water.refresh();water.show();QApplication.processEvents()
    water.grab().save(str(root/'watermark-editor.png'));water.rendered().save(root/'watermark-result.png');water.close()
    layout=TemplateLayoutEditor(template,values);layout.move_box([80,230,740,150]);layout.refresh();layout.show();QApplication.processEvents()
    layout.grab().save(str(root/'template-editor.png'));layout.save_to(root/'edited-template.json');layout.close()
    assert imaging.render_template(root/'edited-template.json',values).size==base.size
    return {'watermark_editor':True,'template_editor':True,'photoshop_render_verified':False}
