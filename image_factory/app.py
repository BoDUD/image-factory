import json
import multiprocessing
import sys
import threading
import traceback
import zipfile
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QThread, QUrl, QStandardPaths, QTimer
from PySide6.QtGui import QPixmap, QDesktopServices, QFontDatabase, QFont
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFileDialog, QMessageBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QTextEdit,
    QTabWidget, QFormLayout, QSplitter, QInputDialog, QListWidget)
from .data import read_customers, auto_bind, write_json, digest, stable_hash, safe_name, sheets
from . import imaging
from .jobs import Queue, sources
from .photoshop import Photoshop


class Work(QThread):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(int, int, str, str)

    def __init__(self, fn):
        super().__init__(); self.fn = fn
        self.cancel = threading.Event(); self.pause = threading.Event()

    def run(self):
        try: self.result.emit(self.fn(self))
        except Exception as e: self.error.emit(str(e))


class Drop(QPushButton):
    files = Signal(list)

    def __init__(self, title, extensions):
        super().__init__(title); self.extensions = extensions
        self.setAcceptDrops(True); self.setMinimumHeight(90); self.setObjectName("drop")
        self.clicked.connect(self.browse)

    def browse(self):
        paths,_ = QFileDialog.getOpenFileNames(self,"选择文件", "", "文件 ("+" ".join("*"+x for x in self.extensions)+")")
        if paths: self.files.emit(paths)

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()

    def dropEvent(self,event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths: self.files.emit(paths); event.acceptProposedAction()


def button(text, fn):
    b=QPushButton(text);b.clicked.connect(fn);return b


class Window(QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle("Image Factory · 本地出图工坊");self.resize(1220,840)
        self.store=Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        self.store.mkdir(parents=True,exist_ok=True)
        self.worker=None;self.template=None;self.layers=[];self.fields=[];self.headers=[];self.rows=[];self.images=[]
        self.last_batch=None;self.customer_path=None;self.collection=[];self.water_offset=None
        central=QWidget();self.setCentralWidget(central);layout=QVBoxLayout(central)
        title=QLabel("IMAGE FACTORY   /   本地出图工坊");title.setObjectName("title");layout.addWidget(title)
        self.hint=QLabel("拖入模板与客户信息，配置一次，批量交付。素材默认保存在本地。");layout.addWidget(self.hint)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        self.build_template();self.build_tools();self.build_library();self.build_delivery();self.build_status();self.build_animation()
        bottom=QHBoxLayout();self.output=QLineEdit(str(Path.home()/"Pictures/ImageFactory"))
        bottom.addWidget(QLabel("成品目录"));bottom.addWidget(self.output,1)
        bottom.addWidget(button("选择",self.select_output));bottom.addWidget(button("打开目录",self.open_output))
        layout.addLayout(bottom)
        row=QHBoxLayout();self.progress=QProgressBar();row.addWidget(self.progress,1)
        self.pause_button=button("暂停",self.pause_job);row.addWidget(self.pause_button)
        row.addWidget(button("取消后续任务",self.cancel_job));layout.addLayout(row)
        self.log=QTextEdit();self.log.setReadOnly(True);self.log.setMaximumHeight(120);layout.addWidget(self.log)

    def build_template(self):
        tab=QWidget();box=QVBoxLayout(tab);drops=QHBoxLayout()
        self.template_drop=Drop("① 拖入 PSD / JSON 模板\n或点击选择",[".psd",".json"])
        self.data_drop=Drop("② 拖入客户 Excel / CSV / TXT\n或点击选择",[".xlsx",".csv",".txt"])
        self.template_drop.files.connect(self.route_files);self.data_drop.files.connect(self.route_files)
        drops.addWidget(self.template_drop);drops.addWidget(self.data_drop);box.addLayout(drops)
        row=QHBoxLayout();row.addWidget(button("生成并载入示例",self.demo));row.addWidget(button("读取 PS 当前文档副本",self.current_ps))
        row.addWidget(button('导入模板素材包',self.import_template_bundle));row.addWidget(button('导出模板素材包',self.export_template_bundle))
        self.encoding=QComboBox();self.encoding.addItems(["utf-8-sig","gb18030"]);row.addWidget(QLabel("名单编码"));row.addWidget(self.encoding)
        self.format=QComboBox();self.format.addItems(["png","jpg"]);row.addWidget(QLabel("格式"));row.addWidget(self.format)
        row.addStretch();box.addLayout(row)
        options=QHBoxLayout();self.naming=QLineEdit('{customer}_{template}_{row_id}');self.naming.setToolTip('支持 {customer} {template} {row_id} {date} {index}')
        options.addWidget(QLabel('命名'));options.addWidget(self.naming,1);self.group=QComboBox()
        for label,key in [('不分类','none'),('按客户','customer'),('按模板','template')]:self.group.addItem(label,key)
        options.addWidget(self.group);box.addLayout(options)
        split=QSplitter();left=QWidget();v=QVBoxLayout(left)
        v.addWidget(QLabel("③ 字段匹配（首次设置后自动记忆）"))
        self.mapping=QTableWidget(0,3);self.mapping.setHorizontalHeaderLabels(["模板字段","客户信息列","最大宽度 px / PS"])
        self.mapping.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);v.addWidget(self.mapping)
        self.data_table=QTableWidget();self.data_table.setMaximumHeight(150);v.addWidget(self.data_table)
        split.addWidget(left)
        self.preview=QLabel("试出一张，确认效果");self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter);self.preview.setMinimumWidth(340);self.preview.setObjectName("preview")
        split.addWidget(self.preview);box.addWidget(split,1)
        row=QHBoxLayout();row.addWidget(button("新建模板",self.create_template));row.addWidget(button("保存字段配置",self.save_mapping));row.addWidget(button('拖动编辑模板布局',self.edit_template_layout));row.addWidget(button("试出第一张",self.preview_one))
        start=button("一键改图 →",self.start_templates);start.setObjectName("primary");row.addWidget(start)
        box.addLayout(row);self.tabs.addTab(tab,"一键改图")
        collection=QHBoxLayout();collection.addWidget(button('加入多模板批次',self.add_collection));self.collection_label=QLabel('0 个模板 / 0 张');collection.addWidget(self.collection_label)
        collection.addWidget(button('查看 / 移除模板',self.edit_collection));collection.addWidget(button('运行多模板批次',self.run_collection));box.addLayout(collection)

    def add_collection(self):
        try:
            recipe,rows=self.recipe();self.save_mapping();self.collection.append((recipe,rows));self.collection_count()
        except Exception as e:self.fail(str(e))

    def collection_count(self):
        self.collection_label.setText(f'{len(self.collection)} 个模板 / {sum(len(r) for _,r in self.collection)} 张')

    def edit_collection(self):
        if not self.collection:self.fail('批次为空');return
        choices=[f'{i+1}. {Path(r["template"]).name} — {len(rows)} 张' for i,(r,rows) in enumerate(self.collection)]
        choice,ok=QInputDialog.getItem(self,'移除模板','各模板保留加入时的名单与字段快照。选择要移除的项：',choices,0,False)
        if ok:self.collection.pop(choices.index(choice));self.collection_count()

    def run_collection(self):
        try:
            from .jobs import combine
            recipe,rows=combine(self.collection,self.format.currentText(),self.naming.text(),self.group.currentData())
            self.run_batch(recipe,rows)
        except Exception as e:self.fail(str(e))

    def build_tools(self):
        tab=QWidget();v=QVBoxLayout(tab)
        drop=Drop("拖入多张 PNG / JPG 图片，批量贴膜或处理",[".png",".jpg",".jpeg",".webp"])
        drop.files.connect(self.load_images);v.addWidget(drop)
        self.image_count=QLabel("尚未选择图片");v.addWidget(self.image_count)
        form=QFormLayout();self.overlay=QLineEdit();row=QHBoxLayout();row.addWidget(self.overlay);row.addWidget(button("选择水印",self.select_overlay));form.addRow("透明水印",row)
        self.scale=QDoubleSpinBox();self.scale.setRange(.01,2);self.scale.setValue(.3);self.scale.setSingleStep(.05);form.addRow("水印宽度 / 画布宽度",self.scale)
        self.opacity=QDoubleSpinBox();self.opacity.setRange(0,1);self.opacity.setSingleStep(.1);self.opacity.setValue(.65);form.addRow("透明度",self.opacity)
        self.position=QComboBox();self.position.addItems(["bottom-right","center","top-left","custom"]);form.addRow("锚点（custom 为拖动位置）",self.position)
        self.blend=QComboBox();self.blend.addItems(["normal","multiply","screen","overlay"]);form.addRow("混合模式",self.blend)
        self.tile=QCheckBox("覆盖画布平铺");form.addRow(self.tile)
        self.gap=QSpinBox();self.gap.setRange(0,500);self.gap.setValue(30);form.addRow("边距 / 平铺间距",self.gap)
        v.addLayout(form)
        row=QHBoxLayout();row.addWidget(button("贴膜预览",self.preview_watermark));row.addWidget(button("批量贴膜",self.start_watermark));row.addWidget(button("保存贴膜预设",self.save_preset));row.addWidget(button("载入预设",self.load_preset));v.addLayout(row)
        v.addWidget(button('打开可视化编辑 · 拖动水印与缩放',self.edit_watermark))
        row=QHBoxLayout();self.operation=QComboBox()
        for label,key in [("等比调整宽度","resize"),("水平镜像","mirror"),("上下镜像","flip"),("中心方形裁切","square"),("高斯模糊","blur"),("马赛克","mosaic")]:self.operation.addItem(label,key)
        row.addWidget(self.operation);self.amount=QSpinBox();self.amount.setRange(1,10000);self.amount.setValue(512);row.addWidget(self.amount)
        row.addWidget(button("批量处理",self.start_transform));v.addLayout(row)
        row=QHBoxLayout();self.columns=QSpinBox();self.columns.setRange(1,12);self.columns.setValue(3);row.addWidget(QLabel("宫格列数"));row.addWidget(self.columns)
        row.addWidget(button("生成宫格预览图",self.make_collage));row.addWidget(button("二维码生成",self.make_qr));v.addLayout(row)
        v.addStretch();self.tabs.addTab(tab,"贴膜与工具箱")

    def build_library(self):
        tab=QWidget();v=QVBoxLayout(tab);row=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText("按文件名搜索")
        self.search.textChanged.connect(self.filter_library);row.addWidget(self.search);row.addWidget(button("载入图片文件夹",self.library_folder));v.addLayout(row)
        self.library=QListWidget();self.library.itemDoubleClicked.connect(lambda item:self.show_image(item.data(Qt.ItemDataRole.UserRole)));v.addWidget(self.library)
        v.addWidget(QLabel("引用本地原文件；双击查看。搜索和移除记录不改动原图。"))
        v.addWidget(button("选中图片送到工具箱",self.library_to_tools));self.library.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.tabs.addTab(tab,"本地图库")

    def build_delivery(self):
        tab=QWidget();v=QVBoxLayout(tab);v.addWidget(QLabel("任务记录与本地交付\n从成品目录读取批次；恢复前校验输入哈希，ZIP 只包含验证成功的文件。"))
        row=QHBoxLayout();row.addWidget(button("刷新批次",self.refresh_batches));row.addWidget(button("恢复选中批次",self.resume_batch));row.addWidget(button("导出成功成品 ZIP",self.export_zip));v.addLayout(row)
        self.batch_list=QListWidget();v.addWidget(self.batch_list);self.tabs.addTab(tab,"任务与交付")

    def build_status(self):
        tab=QWidget();v=QVBoxLayout(tab);v.addWidget(QLabel("引擎状态与实现范围"));self.ps_status=QLabel("Photoshop：尚未连接")
        v.addWidget(self.ps_status);v.addWidget(button("检测 Photoshop",self.probe_ps))
        t=QTextEdit();t.setReadOnly(True);t.setPlainText("当前版本 0.5.0\n\n已实现：多模板批次、拖拽名单、字段记忆、自定义命名、客户/模板分类目录、JSON 实图渲染、PSD 桥接、静态/GIF 贴膜、图片工具、宫格、二维码、本地图库、任务恢复及 ZIP。\n\nPhotoshop 桥接需要 Windows 桌面 Photoshop。普通文字层已编写适配，复杂 PSD、字体和未保存文档保护需要目标版本实测。\n\n已新增：拖动水印、等比缩放、JSON 文字和图片区域布局编辑。\n\n后续阶段：视频、人脸蒙版、智能对象深层修改、字体联网补齐、隐形标与邮件/网盘。\n\nQQ 指令、闪传及群管理需要逐项验证官方接口。本版本不模拟发送成功、不收集外部账号密码。")
        v.addWidget(t);self.tabs.addTab(tab,"连接与范围")

    def build_animation(self):
        tab=QWidget();v=QVBoxLayout(tab)
        v.addWidget(QLabel("GIF 贴膜与关键帧停留\n沿用贴膜页的水印、锚点、透明度和平铺设置。保留循环及各帧时长，支持透明 GIF。"))
        self.gif_input=QLineEdit();row=QHBoxLayout();row.addWidget(self.gif_input);row.addWidget(button("选择 GIF",self.select_gif));v.addLayout(row)
        form=QFormLayout();self.hold_frame=QSpinBox();self.hold_frame.setRange(-1,499);self.hold_frame.setValue(-1);form.addRow("停留帧（从 0 开始，-1 不停留）",self.hold_frame)
        self.hold_ms=QSpinBox();self.hold_ms.setRange(0,60000);self.hold_ms.setSingleStep(100);self.hold_ms.setValue(1000);form.addRow("额外停留毫秒",self.hold_ms);v.addLayout(form)
        v.addWidget(button("选择输出位置并生成 GIF",self.make_gif))
        v.addWidget(QLabel("最多 500 帧及 8000 万累计像素。GIF 仅支持二值透明，半透明边缘可能有变化。\n视频、人脸避让和多动画宫格仍为后续阶段；此工具不会把视频假装成 GIF 处理成功。"))
        v.addStretch();self.tabs.addTab(tab,"GIF 动态贴膜")

    def select_gif(self):
        path,_=QFileDialog.getOpenFileName(self,"选择 GIF","","GIF (*.gif)")
        if path:self.gif_input.setText(path)

    def make_gif(self):
        if not self.gif_input.text() or not self.overlay.text():self.fail("请先选择 GIF，并在贴膜页选择水印");return
        destination,_=QFileDialog.getSaveFileName(self,"保存动态图","watermarked.gif","GIF (*.gif)")
        if not destination:return
        source=self.gif_input.text();overlay=self.overlay.text();options=self.water_options();frame=self.hold_frame.value();hold=self.hold_ms.value()
        def run(w):
            from .media import watermark_gif
            return watermark_gif(source,overlay,destination,options,w.cancel.is_set,lambda i,n:w.progress.emit(i,n,'GIF','处理中'),None if frame<0 else frame,hold)
        self.launch(run,lambda path:self.log.append("GIF 已生成："+path))

    def fail(self,message):
        self.log.append(message);QMessageBox.warning(self,"需要处理",message)

    def launch(self,fn,done=None):
        if self.worker and self.worker.isRunning():self.fail("已有任务运行，请等待或取消后续任务");return
        worker=Work(fn);self.worker=worker
        self.tabs.setEnabled(False);self.output.setReadOnly(True)
        worker.progress.connect(lambda i,n,f,s:(self.progress.setValue(round(i/n*100)),self.log.append(f"{i}/{n}  {f}：{s}")))
        worker.error.connect(self.fail)
        if done:worker.result.connect(done)
        worker.finished.connect(lambda:(self.pause_button.setText("暂停"),self.tabs.setEnabled(True),self.output.setReadOnly(False)))
        worker.start()

    def select_output(self):
        if self.worker and self.worker.isRunning():return
        folder=QFileDialog.getExistingDirectory(self,"成品目录",self.output.text())
        if folder:self.output.setText(folder)

    def open_output(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.output.text()))

    def route_files(self,paths):
        templates=[p for p in paths if Path(p).suffix.lower() in {".psd",".json"}]
        customers=[p for p in paths if Path(p).suffix.lower() in {".xlsx",".csv",".txt"}]
        if len(customers)>1:self.fail("一次请选择一份客户名单");return
        if not templates and not customers:self.fail("请拖入 PSD/JSON 模板或 XLSX/CSV/TXT 名单");return
        if customers and not self.load_customers(customers[0]):return
        if len(templates)>1:self.load_many(templates)
        elif templates:self.load_template(templates[0])

    def load_many(self,paths):
        if not self.rows:self.fail('请先导入客户名单');return
        headers=list(self.headers);rows=[dict(row) for row in self.rows];customer_path=self.customer_path;store=self.store
        def run(w):
            from .templates import prepare_many
            ps=Photoshop()
            try:return prepare_many(paths,headers,rows,customer_path,store,lambda path:ps.call('inspect',template=path))
            finally:ps.close()
        def done(entries):
            self.collection.extend(entries);self.collection_count();self.log.append(f'已加入 {len(entries)} 个模板。点击“运行多模板批次”开始。')
        self.launch(run,done)

    def load_customers(self,path):
        try:
            sheet=None
            if Path(path).suffix.lower()==".xlsx":
                names=sheets(path)
                if len(names)>1:
                    sheet,ok=QInputDialog.getItem(self,"工作表","选择客户信息表",names,0,False)
                    if not ok:return
            self.headers,self.rows=read_customers(path,sheet,self.encoding.currentText());self.customer_path=str(Path(path).resolve())
            self.data_drop.setText(f"客户名单：{Path(path).name}\n{len(self.rows)} 条有效记录")
            self.data_table.setColumnCount(len(self.headers));self.data_table.setHorizontalHeaderLabels(self.headers);self.data_table.setRowCount(min(5,len(self.rows)))
            for i,row in enumerate(self.rows[:5]):
                for j,key in enumerate(self.headers):self.data_table.setItem(i,j,QTableWidgetItem(row[key]))
            self.refresh_mapping()
            return True
        except Exception as e:self.fail(str(e));return False

    def load_template(self,path):
        path=str(Path(path).resolve())
        if Path(path).suffix.lower()==".json":
            try:self.template=path;self.fields=imaging.inspect_template(path);self.layers=[];self.template_ready()
            except Exception as e:self.template=None;self.fail(str(e))
        else:
            def run(w):
                ps=Photoshop()
                try:return ps.call("inspect",template=path)
                finally:ps.close()
            def done(result):
                self.template=path;self.layers=result["layers"];self.fields=list(dict.fromkeys(l["field"] for l in self.layers));self.template_ready()
            self.launch(run,done)

    def template_ready(self):
        self.template_drop.setText(f"模板：{Path(self.template).name}\n{len(self.fields)} 个文字 / 图片字段")
        self.refresh_mapping()

    def config_path(self):
        return self.store/"mappings"/(stable_hash(self.template)+".json")

    def refresh_mapping(self):
        mapping=auto_bind(self.fields,self.headers);saved={}
        if self.template and self.config_path().exists():
            try:
                saved=json.loads(self.config_path().read_text(encoding="utf-8"))
                if saved.get("hash")==digest(self.template):mapping.update({k:v for k,v in saved.get("mapping",{}).items() if v in self.headers})
                else:self.log.append("模板已改变，旧绑定未自动套用，请重新确认")
            except Exception:self.log.append("旧字段配置无效，请重新绑定")
        self.mapping.setRowCount(len(self.fields))
        for i,field in enumerate(self.fields):
            item=QTableWidgetItem(field);item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);self.mapping.setItem(i,0,item)
            combo=QComboBox();combo.addItem("请选择信息列","")
            for head in self.headers:combo.addItem(head,head)
            idx=combo.findData(mapping.get(field,""));combo.setCurrentIndex(max(0,idx));self.mapping.setCellWidget(i,1,combo)
            width=QSpinBox();width.setRange(1,30000);width.setValue(int(saved.get("widths",{}).get(field,next((x["width"] for x in self.layers if x["field"]==field),600))))
            self.mapping.setCellWidget(i,2,width)

    def bindings(self):
        if not self.template or not self.rows:raise ValueError("请先载入有效模板与客户信息")
        mapping={f:self.mapping.cellWidget(i,1).currentData() for i,f in enumerate(self.fields)}
        if any(not v for v in mapping.values()):raise ValueError("请为每个模板字段选择客户信息列")
        values=[]
        for i,row in enumerate(self.rows):
            item={f:row[col] for f,col in mapping.items()}
            if any(not str(v).strip() for v in item.values()):raise ValueError(f"第 {i+1} 条客户信息缺少必填字段")
            item["__index"]=row["__index"];values.append(item)
        return mapping,values

    def save_mapping(self):
        try:
            mapping,_=self.bindings()
            write_json(self.config_path(),{"hash":digest(self.template),"mapping":mapping,"widths":{f:self.mapping.cellWidget(i,2).value() for i,f in enumerate(self.fields)}})
            self.log.append("字段配置已保存")
        except Exception as e:self.fail(str(e))

    def recipe(self):
        mapping,values=self.bindings();template=self.template
        mode="psd" if Path(template).suffix.lower()==".psd" else "template"
        files=[template] if mode=="psd" else imaging.dependencies(template)
        if self.customer_path:files.append(self.customer_path)
        if mode=="template":
            spec=json.loads(Path(template).read_text(encoding="utf-8"))
            for slot in spec.get("slots",[]):
                for row in values:
                    source=Path(row[slot["field"]])
                    if not source.is_absolute():source=Path(self.customer_path).parent/source
                    row[slot["field"]]=str(source.resolve());files.append(source)
        recipe={"mode":mode,"template":template,"format":self.format.currentText(),"sources":sources(files),'naming':self.naming.text(),'group':self.group.currentData()}
        if mode=="psd":
            widths={f:self.mapping.cellWidget(i,2).value() for i,f in enumerate(self.fields)}
            recipe["bindings"]=[dict(l,max_width=widths[l["field"]],min_size=12) for l in self.layers]
        return recipe,values

    def start_templates(self):
        try:
            recipe,values=self.recipe();self.save_mapping();self.run_batch(recipe,values)
        except Exception as e:self.fail(str(e))

    def run_batch(self,recipe,values,batch=None):
        output=self.output.text()
        def run(w):
            q=Queue(output)
            try:
                key=batch or q.plan(recipe,values)
                result=q.run(key,w.progress.emit,w.cancel.is_set,w.pause.is_set)
                return {"batch":key,"output":output,"items":result}
            finally:q.close()
        def done(result):
            self.last_batch=result
            succeeded=sum(x[3]=="succeeded" for x in result["items"])
            failed=sum(x[3]=="failed" for x in result["items"])
            self.log.append(f"批次停止：成功 {succeeded}，失败 {failed}，未处理 {len(result['items'])-succeeded-failed}")
            first=next((x[2] for x in result["items"] if x[3]=="succeeded"),None)
            if first:self.show_image(str(Path(result["output"])/first))
        self.launch(run,done)

    def preview_one(self):
        try:
            recipe,values=self.recipe();destination=str(self.store/"preview.png")
            def run(w):
                if recipe["mode"]=="psd":
                    ps=Photoshop()
                    try:ps.call("render",template=recipe["template"],bindings=recipe["bindings"],values=values[0],output=destination,format="png")
                    finally:ps.close()
                else:imaging.save_image(imaging.render_template(recipe["template"],values[0]),destination)
                return destination
            self.launch(run,self.show_image)
        except Exception as e:self.fail(str(e))

    def show_image(self,path):
        pix=QPixmap(str(path))
        if pix.isNull():return
        self.preview.setPixmap(pix.scaled(450,390,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        self.preview.setToolTip(str(path))
        self.log.append("预览已更新："+str(path))

    def current_ps(self):
        import uuid
        path=str(self.store/("snapshot_"+uuid.uuid4().hex+".psd"))
        def run(w):
            ps=Photoshop()
            try:
                ps.call("snapshot",current=True,output=path)
                return ps.call("inspect",template=path)
            finally:ps.close()
        def done(result):
            self.template=path;self.layers=result["layers"];self.fields=list(dict.fromkeys(l["field"] for l in self.layers));self.template_ready()
        self.launch(run,done)

    def probe_ps(self):
        from .diagnostics import photoshop_environment
        environment=photoshop_environment()
        if not environment['registered']:
            self.ps_status.setText(environment['message']);self.log.append('环境检查：'+environment['message']);return
        def run(w):
            ps=Photoshop()
            try:return ps.call("probe",timeout=30)
            finally:ps.close()
        self.launch(run,lambda result:self.ps_status.setText("Photoshop 已连接："+result["version"]))

    def demo(self):
        from .demo import create_demo
        folder=self.store/"example";create_demo(folder)
        self.load_customers(str(folder/"customers.csv"));self.load_template(str(folder/"greeting.json"))

    def load_images(self,paths):
        allowed={".png",".jpg",".jpeg",".webp",".bmp"}
        if any(Path(p).suffix.lower() not in allowed for p in paths):self.fail("静态工具只接受 PNG/JPG/WebP/BMP");return
        self.images=list(dict.fromkeys(str(Path(p).resolve()) for p in paths));self.image_count.setText(f"已选择 {len(self.images)} 张图片")

    def select_overlay(self):
        path,_=QFileDialog.getOpenFileName(self,"选择透明水印","","图片 (*.png *.webp)")
        if path:self.overlay.setText(path)

    def water_options(self):
        if self.position.currentText()=='custom' and self.water_offset is None:raise ValueError('请先用可视化编辑设置自由位置')
        return dict(scale=self.scale.value(),opacity=self.opacity.value(),position=self.position.currentText(),tile=self.tile.isChecked(),gap=self.gap.value(),blend=self.blend.currentText(),offset=self.water_offset if self.position.currentText()=='custom' else None)

    def edit_watermark(self):
        if not self.images:self.fail('请先在贴膜页选择底图和水印');return
        try:
            from .editor import WatermarkEditor
            editor=WatermarkEditor(imaging.load_image(self.images[0]),imaging.load_image(self.overlay.text()),self.water_options(),self)
            if editor.exec():
                options=editor.options
                self.scale.setDecimals(6);self.scale.setValue(options['scale']);self.opacity.setValue(options['opacity']);self.tile.setChecked(False)
                self.water_offset=options.get('offset')
                if self.water_offset is not None:self.position.setCurrentText('custom')
                self.log.append('编辑已应用到当前贴膜设置；点击“批量贴膜”应用整批，或保存预设。')
        except Exception as e:self.fail(str(e))

    def create_template(self):
        self.open_designer(None)

    def export_template_bundle(self):
        if not self.template or Path(self.template).suffix.lower()!='.json':self.fail('请先保存并载入 JSON 模板');return
        path,_=QFileDialog.getSaveFileName(self,'导出模板和背景、预览框、字体素材','template-bundle.zip','ZIP (*.zip)')
        if not path:return
        try:
            from .bundles import export_bundle
            result=export_bundle(self.template,path);self.log.append('模板素材包已导出：'+str(result)+'；不包含客户名单和客户头像。')
        except Exception as e:self.fail(str(e))

    def import_template_bundle(self):
        path,_=QFileDialog.getOpenFileName(self,'导入模板素材包','','ZIP (*.zip)')
        if not path:return
        try:
            from .bundles import import_bundle
            template=import_bundle(path,self.store/'templates');self.load_template(str(template));self.log.append('素材包已校验并载入，客户名单请另行导入。')
        except Exception as e:self.fail(str(e))

    def edit_template_layout(self):
        if not self.template or Path(self.template).suffix.lower()!='.json':self.fail('请载入 JSON 模板，或点击新建模板');return
        self.open_designer(self.template)

    def open_designer(self,path):
        try:
            from .designer import TemplateDesigner
            editor=TemplateDesigner(path,self)
            if not editor.exec():return
            destination,_=QFileDialog.getSaveFileName(self,'保存新模板','my-template.json','JSON (*.json)')
            if not destination:return
            editor.save_to(destination);self.load_template(destination)
            self.log.append('模板已载入；导入客户名单并绑定字段即可出图。自动编号不需要名单列。')
        except Exception as e:self.fail(str(e))

    def image_recipe(self,mode):
        if not self.images:raise ValueError("请先选择图片")
        recipe={"mode":mode,"format":self.format.currentText()};files=list(self.images)
        if mode=="watermark":recipe.update(overlay=self.overlay.text(),options=self.water_options());files.append(self.overlay.text())
        else:recipe.update(operation=self.operation.currentData(),amount=self.amount.value())
        recipe["sources"]=sources(files)
        return recipe,[{"input":p,"__name":Path(p).stem} for p in self.images]

    def start_watermark(self):
        try:self.run_batch(*self.image_recipe("watermark"))
        except Exception as e:self.fail(str(e))

    def start_transform(self):
        try:self.run_batch(*self.image_recipe("transform"))
        except Exception as e:self.fail(str(e))

    def preview_watermark(self):
        try:
            recipe,rows=self.image_recipe("watermark");path=str(self.store/"watermark-preview.png")
            def run(w):
                imaging.save_image(imaging.watermark(imaging.load_image(rows[0]["input"]),imaging.load_image(recipe["overlay"]),**recipe["options"]),path)
                return path
            self.launch(run,lambda p:(self.show_image(p),self.tabs.setCurrentIndex(0)))
        except Exception as e:self.fail(str(e))

    def save_preset(self):
        path,_=QFileDialog.getSaveFileName(self,"保存预设","watermark.json","JSON (*.json)")
        if path:
            try:write_json(path,dict(version=2,overlay=self.overlay.text(),options=self.water_options()))
            except Exception as e:self.fail(str(e))

    def load_preset(self):
        path,_=QFileDialog.getOpenFileName(self,"载入预设","","JSON (*.json)")
        if not path:return
        try:
            spec=json.loads(Path(path).read_text(encoding="utf-8"))
            if spec["version"] not in (1,2):raise ValueError("预设版本不兼容")
            opts=spec["options"];self.overlay.setText(spec["overlay"]);self.scale.setValue(opts["scale"]);self.opacity.setValue(opts["opacity"])
            self.position.setCurrentText(opts["position"]);self.tile.setChecked(opts["tile"]);self.gap.setValue(opts["gap"]);self.blend.setCurrentText(opts["blend"])
            self.water_offset=opts.get('offset');self.scale.setDecimals(6);self.scale.setValue(opts['scale'])
        except Exception as e:self.fail("预设无效："+str(e))

    def make_collage(self):
        if not self.images:self.fail("请先选择图片");return
        path,_=QFileDialog.getSaveFileName(self,"保存宫格","collage.png","PNG (*.png)")
        if not path:return
        files=list(self.images);columns=self.columns.value()
        def run(w):
            imaging.save_image(imaging.collage([imaging.load_image(f) for f in files],columns),path);return path
        self.launch(run,lambda p:(self.show_image(p),self.tabs.setCurrentIndex(0)))

    def make_qr(self):
        text,ok=QInputDialog.getText(self,"二维码","输入需要编码的文字或链接")
        if not ok or not text:return
        path,_=QFileDialog.getSaveFileName(self,"保存二维码","qrcode.png","PNG (*.png)")
        if path:
            try:
                import qrcode
                qrcode.make(text).save(path);self.show_image(path);self.tabs.setCurrentIndex(0)
            except Exception as e:self.fail(str(e))

    def library_folder(self):
        from PySide6.QtWidgets import QListWidgetItem
        folder=QFileDialog.getExistingDirectory(self,"选择图库")
        if not folder:return
        self.library.clear()
        for p in sorted(Path(folder).iterdir()):
            if p.is_file() and p.suffix.lower() in {".png",".jpg",".jpeg",".webp"}:
                item=QListWidgetItem(p.name);item.setData(Qt.ItemDataRole.UserRole,str(p));self.library.addItem(item)

    def filter_library(self,text):
        for i in range(self.library.count()):
            item=self.library.item(i);item.setHidden(text.casefold() not in item.text().casefold())

    def library_to_tools(self):
        self.load_images([i.data(Qt.ItemDataRole.UserRole) for i in self.library.selectedItems()]);self.tabs.setCurrentIndex(1)

    def refresh_batches(self):
        from PySide6.QtWidgets import QListWidgetItem
        try:
            q=Queue(self.output.text())
            try:
                self.batch_list.clear()
                for key,created in q.batches():
                    items=q.items(key);done=sum(x[3]=="succeeded" for x in items)
                    item=QListWidgetItem(f"{created}  ·  {done}/{len(items)}  ·  {key[:8]}");item.setData(Qt.ItemDataRole.UserRole,key);self.batch_list.addItem(item)
            finally:q.close()
        except Exception as e:self.fail(str(e))

    def resume_batch(self):
        item=self.batch_list.currentItem()
        if not item:self.fail("请选择一个批次");return
        self.run_batch(None,None,item.data(Qt.ItemDataRole.UserRole))

    def export_zip(self):
        item=self.batch_list.currentItem()
        if not item:self.fail("请选择一个批次");return
        path,_=QFileDialog.getSaveFileName(self,"导出成品 ZIP","delivery.zip","ZIP (*.zip)")
        if not path:return
        output=self.output.text();key=item.data(Qt.ItemDataRole.UserRole)
        def run(w):
            from .delivery import export_batch
            return export_batch(output,key,path)
        self.launch(run,lambda result:self.log.append(f"交付 ZIP 已生成：{result}"))

    def pause_job(self):
        if self.worker and self.worker.isRunning():
            if self.worker.pause.is_set():self.worker.pause.clear();self.pause_button.setText("暂停")
            else:self.worker.pause.set();self.pause_button.setText("继续");self.log.append("当前图片处理完后暂停")

    def cancel_job(self):
        if self.worker and self.worker.isRunning():self.worker.cancel.set();self.log.append("当前操作完成后停止派发，不强制关闭 Photoshop")

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel.set();event.ignore();self.log.append("已请求取消，请等待当前操作结束后关闭窗口")
        else:event.accept()


STYLE="""
QWidget { font-family:'Microsoft YaHei','Segoe UI';font-size:13px;color:#203449;background:#f4f7fb; }
QLabel#title {font-size:24px;font-weight:700;padding:10px 0;color:#173c55;}
QPushButton {background:white;border:1px solid #cfdae5;border-radius:7px;padding:9px 14px;}
QPushButton:hover {background:#e4f4f4;border-color:#27988e;}
QPushButton#drop {border:2px dashed #8dbebd;background:#edf9f7;color:#17635e;font-size:15px;}
QPushButton#primary {background:#13877e;color:white;font-weight:bold;}
QLineEdit,QTextEdit,QTableWidget,QListWidget,QComboBox,QSpinBox,QDoubleSpinBox {background:white;border:1px solid #d5dfe8;border-radius:4px;padding:5px;}
QTabBar::tab {padding:12px 24px;} QTabBar::tab:selected {color:#087e73;background:white;}
QLabel#preview {background:#e5ebf1;border-radius:10px;color:#718399;}
QProgressBar {border:1px solid #d5dfe8;border-radius:4px;text-align:center;} QProgressBar::chunk {background:#27a295;}
"""


def main():
    multiprocessing.freeze_support()
    app=QApplication(sys.argv);app.setOrganizationName("ImageFactory");app.setApplicationName("ImageFactory")
    configure_fonts(app)
    app.setStyleSheet(STYLE);window=Window();window.show()
    if '--smoke-dir' in sys.argv:
        root=Path(sys.argv[sys.argv.index('--smoke-dir')+1]).resolve();root.mkdir(parents=True,exist_ok=True)
        window.store=root/'state';window.store.mkdir(exist_ok=True);window.output.setText(str(root/'output'))
        window.demo();window.add_collection()
        second=window.store/'example/second.json'
        spec=json.loads(Path(window.template).read_text(encoding='utf-8'));spec['background']='#ffeedd';write_json(second,spec)
        window.load_template(str(second));window.add_collection();window.group.setCurrentIndex(window.group.findData('customer'));window.run_collection()
        def finish_smoke():
            if window.worker and window.worker.isRunning():return
            timer.stop()
            ok=bool(window.last_batch and all(x[3]=='succeeded' for x in window.last_batch['items']))
            window.grab().save(str(root/'desktop.png'))
            editor_result={}
            try:
                from .editor_smoke import run
                editor_result=run(root,window.template)
            except Exception as e:
                ok=False;editor_result={'error':str(e)}
            write_json(root/'result.json',{'ok':ok,'log':window.log.toPlainText(),'editors':editor_result})
            timer.stop();app.exit(0 if ok else 1)
        timer=QTimer();timer.timeout.connect(finish_smoke);timer.start(100)
    sys.exit(app.exec())


def configure_fonts(app):
    path=imaging.font_path()
    if path:
        font_id=QFontDatabase.addApplicationFont(path)
        families=QFontDatabase.applicationFontFamilies(font_id)
        if families:app.setFont(QFont(families[0],10))
