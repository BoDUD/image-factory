/* Fixed script; request is an ASCII JSON object literal supplied by the host. */
(function () {
    function json(v) {
        if (v === null) return 'null';
        if (typeof v === 'string') return '"' + v.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\r/g, '\\r').replace(/\n/g, '\\n').replace(/\t/g, '\\t').replace(/[\x00-\x1f]/g, function(c) { return '\\u' + ('0000'+c.charCodeAt(0).toString(16)).slice(-4); }) + '"';
        if (typeof v === 'number' || typeof v === 'boolean') return String(v);
        var a = [], k;
        if (v instanceof Array) { for (k=0;k<v.length;k++) a.push(json(v[k])); return '['+a.join(',')+']'; }
        for (k in v) if (v.hasOwnProperty(k)) a.push(json(k)+':'+json(v[k]));
        return '{'+a.join(',')+'}';
    }
    var original = app.documents.length ? app.activeDocument : null;
    var source = null, owned = false, copy = null, oldDialogs = app.displayDialogs;
    function getLayer(doc, path) {
        var layer = doc;
        for (var i=0;i<path.length;i++) layer = layer.layers[path[i]];
        return layer;
    }
    try {
        if (request.operation === 'probe') return json({version: app.version, documents: app.documents.length});
        app.displayDialogs = DialogModes.NO;
        if (request.current) {
            if (!original) throw Error('Photoshop 没有打开文档');
            source = original;
        } else {
            var targetFile = new File(request.template);
            for(var d=0;d<app.documents.length;d++) {
                try { if (app.documents[d].fullName.fsName.toLowerCase() === targetFile.fsName.toLowerCase()) source = app.documents[d]; } catch(ignore) {}
            }
            if (source && !source.saved) throw Error('该 PSD 有未保存修改，请先另存为模板，或使用读取当前文档');
            if (!source) { source = app.open(targetFile); owned = true; }
        }
        if (request.operation === 'snapshot') {
            copy = source.duplicate('ImageFactory_snapshot');
            var psdOptions = new PhotoshopSaveOptions(); psdOptions.layers = true;
            copy.saveAs(new File(request.output), psdOptions, true, Extension.LOWERCASE);
            return json({ok:true});
        }
        if (request.operation === 'inspect') {
            var layers=[];
            function walk(container, indices, names) {
                for (var i=0;i<container.layers.length;i++) {
                    var l=container.layers[i], path=indices.concat([i]), label=names.concat([l.name]);
                    if (l.typename === 'LayerSet') walk(l,path,label);
                    else if (l.kind === LayerKind.TEXT) {
                        if(l.textItem.kind === TextType.PARAGRAPHTEXT) throw Error('首版仅支持点文字层，请转换或使用 JSON 模板：'+label.join('/'));
                        var reference=new ActionReference();reference.putIdentifier(charIDToTypeID('Lyr '),l.id);
                        var descriptor=executeActionGet(reference);
                        if(descriptor.hasKey(stringIDToTypeID('textKey'))) {
                            var textDescriptor=descriptor.getObjectValue(stringIDToTypeID('textKey'));
                            if(textDescriptor.hasKey(stringIDToTypeID('textStyleRange')) && textDescriptor.getList(stringIDToTypeID('textStyleRange')).count>1)
                                throw Error('首版不支持混合样式文字，请拆成统一样式字段：'+label.join('/'));
                        }
                        var bounds=l.bounds;
                        layers.push({field:l.name.replace(/^TEXT__/,''), path:path, label:label.join('/'), name:l.name, font:l.textItem.font, width:Math.max(1,bounds[2].as('px')-bounds[0].as('px'))});
                    }
                }
            }
            walk(source,[],[]);
            return json({layers:layers,width:source.width.as('px'),height:source.height.as('px')});
        }
        copy = source.duplicate('ImageFactory_work');
        app.activeDocument = copy;
        var fonts={}; for(var fi=0;fi<app.fonts.length;fi++) fonts[app.fonts[fi].postScriptName]=true;
        for (var n=0;n<request.bindings.length;n++) {
            var b=request.bindings[n], layer=getLayer(copy,b.path);
            if(layer.name!==b.name || layer.typename!=='ArtLayer' || layer.kind!==LayerKind.TEXT) throw Error('模板图层结构改变，请重新绑定');
            if (!fonts[layer.textItem.font]) throw Error('缺少字体: '+layer.textItem.font);
            layer.allLocked=false;
            layer.textItem.contents=String(request.values[b.field]);
            var attempts=0;
            while(layer.bounds[2].as('px')-layer.bounds[0].as('px') > b.max_width) {
                if(layer.textItem.size.as('pt')<=b.min_size || attempts++>150) throw Error('文字超框: '+b.field);
                layer.textItem.size=UnitValue(Math.max(b.min_size,layer.textItem.size.as('pt')-1),'pt');
            }
        }
        if(copy.mode!==DocumentMode.RGB) copy.changeMode(ChangeMode.RGB);
        copy.bitsPerChannel=BitsPerChannelType.EIGHT;
        copy.convertProfile('sRGB IEC61966-2.1',Intent.RELATIVECOLORIMETRIC,true,true);
        if(request.format === 'jpg') {
            var bg=copy.artLayers.add(); bg.name='ImageFactory_white_background';
            bg.move(copy.layers[copy.layers.length-1],ElementPlacement.PLACEAFTER);
            copy.activeLayer=bg; copy.selection.selectAll(); var white=new SolidColor(); white.rgb.hexValue='FFFFFF';
            copy.selection.fill(white); copy.selection.deselect(); copy.flatten();
            var jpg=new JPEGSaveOptions(); jpg.quality=12;
            copy.saveAs(new File(request.output),jpg,true,Extension.LOWERCASE);
        } else copy.saveAs(new File(request.output),new PNGSaveOptions(),true,Extension.LOWERCASE);
        return json({ok:true,width:copy.width.as('px'),height:copy.height.as('px')});
    } catch(e) { return json({error:String(e)}); }
    finally {
        if(copy) try { copy.close(SaveOptions.DONOTSAVECHANGES); } catch(e1) {}
        if(owned && source) try { source.close(SaveOptions.DONOTSAVECHANGES); } catch(e2) {}
        if(original) try { app.activeDocument=original; } catch(e3) {}
        app.displayDialogs=oldDialogs;
    }
}());
