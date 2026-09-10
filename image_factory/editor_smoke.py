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
    from .designer import TemplateDesigner
    designer=TemplateDesigner();designer.preset_frame(2);designer.add_region('number')
    designer.spec['text'][0]['box']=[80,560,740,100]
    designer.spec['text'][-1]['box']=[80,700,500,100]
    designer.spec['text'][-1]['number']['prefix']='VIP-'
    designer.refresh();designer.show();QApplication.processEvents()
    designer.grab().save(str(root/'template-designer.png'));designer.save_to(root/'new-template.json')
    from .bundles import export_bundle,import_bundle
    archive=export_bundle(root/'new-template.json',root/'template-bundle.zip')
    imported=import_bundle(archive,root/'imported')
    expected=imaging.render_template(root/'new-template.json',designer.values)
    actual=imaging.render_template(imported,designer.values)
    assert actual.tobytes()==expected.tobytes();actual.save(root/'frame-result.png');designer.close()
    return {'watermark_editor':True,'template_editor':True,'template_designer':True,'frame_bundle_roundtrip':True,'photoshop_render_verified':False}
