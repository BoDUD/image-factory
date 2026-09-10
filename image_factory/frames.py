"""Built-in transparent preview frames; no external artwork required."""
from PIL import Image,ImageDraw


def create_frame(size,count,path):
    if count not in (1,2,4):raise ValueError('预览框支持单头像、双头像或四宫格')
    w,h=size;cols=1 if count==1 else 2;rows=2 if count==4 else 1
    gap=max(4,round(min(w,h)*.04));cell=max(1,min((w-gap*(cols+1))//cols,int(h*.7-gap*(rows+1))//rows))
    left=(w-cols*cell-(cols-1)*gap)//2
    frame=Image.new('RGBA',size,(0,0,0,0));draw=ImageDraw.Draw(frame);boxes=[]
    for i in range(count):
        x=left+(i%cols)*(cell+gap);y=gap+(i//cols)*(cell+gap);boxes.append([x,y,cell,cell])
        border=max(2,gap//3)
        draw.rectangle((x-border,y-border,x+cell+border-1,y+cell+border-1),fill='#13877e')
        draw.rectangle((x,y,x+cell-1,y+cell-1),fill=(0,0,0,0))
    frame.save(path);return boxes
