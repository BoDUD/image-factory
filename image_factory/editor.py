"""Canvas interaction in source-pixel coordinates, independent of view zoom/DPI."""
import copy
import json
from pathlib import Path
from PySide6.QtCore import Qt,QRectF,QPointF,Signal,QTimer
from PySide6.QtGui import QPainter,QColor,QPen,QImage
from PySide6.QtWidgets import QWidget,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QDialogButtonBox,QDoubleSpinBox,QComboBox
from . import imaging
from .data import write_json

def qimage(im):
    rgba=im.convert('RGBA')
    return QImage(rgba.tobytes(),rgba.width,rgba.height,rgba.width*4,QImage.Format.Format_RGBA8888).copy()

class PlacementCanvas(QWidget):
    changed=Signal(object)

    def __init__(self,image,box,keep_ratio=True,parent=None):
        super().__init__(parent);self.image=qimage(image);self.source_size=image.size;self.box=QRectF(*box);self.keep_ratio=keep_ratio
        self.drag=None;self.setMinimumSize(540,360);self.setMouseTracking(True)

    def viewport_rect(self):
        w,h=self.source_size;s=min((self.width()-32)/w,(self.height()-32)/h)
        return QRectF((self.width()-w*s)/2,(self.height()-h*s)/2,w*s,h*s)

    def to_source(self,point):
        r=self.viewport_rect();return QPointF((point.x()-r.x())*self.source_size[0]/r.width(),(point.y()-r.y())*self.source_size[1]/r.height())

    def to_view(self,point):
        r=self.viewport_rect();return QPointF(r.x()+point.x()*r.width()/self.source_size[0],r.y()+point.y()*r.height()/self.source_size[1])

    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#e4eaf0'));r=self.viewport_rect()
        painter.fillRect(r,QColor('white'));painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform);painter.drawImage(r,self.image)
        selection=QRectF(self.to_view(self.box.topLeft()),self.to_view(self.box.bottomRight()))
        painter.setPen(QPen(QColor('#087f80'),2,Qt.PenStyle.DashLine));painter.drawRect(selection)
        painter.fillRect(QRectF(selection.right()-5,selection.bottom()-5,10,10),QColor('#087f80'));painter.end()

    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton:return
        p=event.position();handle=self.to_view(self.box.bottomRight())
        if abs(p.x()-handle.x())<=12 and abs(p.y()-handle.y())<=12:self.drag='resize'
        elif self.box.contains(self.to_source(p)):self.drag='move'
        else:return
        self.start=self.to_source(p);self.initial=QRectF(self.box);event.accept()

    def mouseMoveEvent(self,event):
        if not self.drag:return
        delta=self.to_source(event.position())-self.start;w,h=self.source_size
        if self.drag=='move':
            x=max(-min(self.initial.width(),w*2)+1,min(w-1,self.initial.x()+delta.x()))
            y=max(-min(self.initial.height(),h*2)+1,min(h-1,self.initial.y()+delta.y()))
            self.box.moveTo(x,y)
        else:
            width=max(w*.01,min(w*2,self.initial.width()+delta.x()))
            height=width*self.initial.height()/self.initial.width() if self.keep_ratio else max(1,min(h*2,self.initial.height()+delta.y()))
            self.box.setWidth(width);self.box.setHeight(height)
        self.changed.emit([self.box.x(),self.box.y(),self.box.width(),self.box.height()]);self.update();event.accept()

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.mouseMoveEvent(event);self.drag=None;event.accept()

class WatermarkEditor(QDialog):
    def __init__(self,base,overlay,options,parent=None):
        super().__init__(parent);self.setWindowTitle('可视化水印编辑');self.resize(930,740)
        self.base=base.copy();self.overlay=overlay.copy();self.options=copy.deepcopy(options);self.options['tile']=False
        self.original=copy.deepcopy(self.options);self.error=None
        rect=imaging.watermark_rect(base.size,overlay.size,self.options.get('scale',.3),self.options.get('position','bottom-right'),self.options.get('gap',30),self.options.get('offset'))
        layout=QVBoxLayout(self);layout.addWidget(QLabel('拖动框内移动水印，拖右下角方块等比缩放。位置按画布比例保存，可应用到整批图片。'))
        if options.get('tile'):layout.addWidget(QLabel('自由定位使用单个水印；点击应用后关闭平铺，取消保留原设置。'))
        self.canvas=PlacementCanvas(base,rect);layout.addWidget(self.canvas,1)
        row=QHBoxLayout();self.size=QDoubleSpinBox();self.size.setRange(.01,2);self.size.setDecimals(6);self.size.setSingleStep(.02);self.size.setValue(options.get('scale',.3))
        self.alpha=QDoubleSpinBox();self.alpha.setRange(0,1);self.alpha.setDecimals(2);self.alpha.setSingleStep(.05);self.alpha.setValue(options.get('opacity',.65))
        row.addWidget(QLabel('宽度比例'));row.addWidget(self.size);row.addWidget(QLabel('透明度'));row.addWidget(self.alpha)
        reset=QPushButton('重置');reset.clicked.connect(self.reset);row.addWidget(reset);layout.addLayout(row)
        self.info=QLabel();layout.addWidget(self.info)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('应用到贴膜设置');self.buttons.accepted.connect(self.accept_checked);self.buttons.rejected.connect(self.reject);layout.addWidget(self.buttons)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.refresh)
        self.canvas.changed.connect(self.move_box);self.size.valueChanged.connect(self.resize_box);self.alpha.valueChanged.connect(self.opacity_changed)
        self.refresh()

    def move_box(self,box):
        x,y,width,height=box;w,h=self.base.size
        self.options.update(offset=[x/w,y/h],scale=round(width/w,6))
        self.size.blockSignals(True);self.size.setValue(width/w);self.size.blockSignals(False);self.timer.start(70)

    def resize_box(self,value):
        self.options['scale']=value
        x,y,w,h=imaging.watermark_rect(self.base.size,self.overlay.size,value,self.options.get('position','bottom-right'),self.options.get('gap',30),self.options.get('offset'))
        self.canvas.box=QRectF(x,y,w,h);self.canvas.update();self.timer.start(70)

    def opacity_changed(self,value):self.options['opacity']=value;self.timer.start(70)

    def rendered(self):return imaging.watermark(self.base,self.overlay,**self.options)

    def refresh(self):
        try:
            self.canvas.box=QRectF(*imaging.watermark_rect(self.base.size,self.overlay.size,self.options.get('scale',.3),self.options.get('position','bottom-right'),self.options.get('gap',30),self.options.get('offset')))
            self.canvas.image=qimage(self.rendered());self.canvas.update();self.error=None
            self.info.setText('预览与批量导出使用相同合成参数。超出画布的部分会被裁切。')
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        except Exception as e:
            self.error=str(e);self.info.setText('无法应用：'+self.error);self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def reset(self):
        self.options=copy.deepcopy(self.original);self.size.blockSignals(True);self.size.setValue(self.options.get('scale',.3));self.size.blockSignals(False)
        self.alpha.blockSignals(True);self.alpha.setValue(self.options.get('opacity',.65));self.alpha.blockSignals(False)
        self.resize_box(self.options.get('scale',.3));self.refresh()

    def accept_checked(self):
        self.timer.stop();self.refresh()
        if not self.error:self.accept()

class TemplateLayoutEditor(QDialog):
    """Move and resize existing text/image boxes; save as a new JSON template."""
    def __init__(self,path,values,parent=None):
        super().__init__(parent);self.setWindowTitle('模板布局编辑');self.resize(930,740)
        self.path=Path(path);self.values=dict(values);self.spec=json.loads(self.path.read_text(encoding='utf-8'))
        self.items=[(kind,i) for kind in ['slots','text'] for i in range(len(self.spec.get(kind,[])))]
        if not self.items:raise ValueError('模板没有可编辑区域')
        preview=imaging.render_template(path,values)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('选择文字或头像区域，拖动位置或右下角调整大小。另存为新模板，不覆盖原稿。'))
        self.selector=QComboBox()
        for kind,i in self.items:self.selector.addItem(('头像 / 图片' if kind=='slots' else '文字')+' · '+self.spec[kind][i]['field'])
        layout.addWidget(self.selector);kind,i=self.items[0]
        self.canvas=PlacementCanvas(preview,self.spec[kind][i]['box'],keep_ratio=False);layout.addWidget(self.canvas,1)
        self.label=QLabel('拖动显示区域边框；点击“刷新成品预览”检查实际排版。');layout.addWidget(self.label)
        refresh=QPushButton('刷新成品预览');refresh.clicked.connect(self.refresh);layout.addWidget(refresh)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);layout.addWidget(self.buttons)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText('另存为新模板')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        self.buttons.accepted.connect(self.accept_checked);self.buttons.rejected.connect(self.reject)
        self.selector.currentIndexChanged.connect(self.select);self.canvas.changed.connect(self.move_box)

    def select(self,index):
        kind,i=self.items[index];self.canvas.box=QRectF(*self.spec[kind][i]['box']);self.canvas.update()

    def move_box(self,box):
        kind,i=self.items[self.selector.currentIndex()];self.spec[kind][i]['box']=[round(v) for v in box];self.label.setText(str(self.spec[kind][i]['box']))

    def portable_spec(self):
        spec=copy.deepcopy(self.spec)
        for key in ['background_image','frame']:
            if spec.get(key):spec[key]=str(imaging.asset(self.path,spec[key]).resolve())
        for item in spec.get('text',[]):
            if item.get('font'):item['font']=str(imaging.asset(self.path,item['font']).resolve())
        return spec

    def refresh(self):
        try:
            result=imaging.render_spec(self.portable_spec(),self.values,self.path)
            self.select(self.selector.currentIndex())
            self.canvas.image=qimage(result);self.canvas.update();self.label.setText('已刷新实际成品预览');return True
        except Exception as e:self.label.setText('排版错误：'+str(e));return False

    def accept_checked(self):
        if self.refresh():self.accept()

    def save_to(self,destination):
        if Path(destination).resolve()==self.path.resolve():raise ValueError('请另存为新模板，不能覆盖原稿')
        if not self.refresh():raise ValueError('模板排版无效，请修正后保存')
        write_json(destination,self.portable_spec())
