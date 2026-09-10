from pathlib import Path
from .data import write_json


def create_demo(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    write_json(folder/"greeting.json",{"version":1,"size":[900,900],"background":"#e7f5f1","text":[
        {"field":"customer","box":[80,300,740,150],"size":88,"min_size":24,"color":"#17564b","align":"center"},
        {"field":"order_id","box":[80,540,740,80],"size":36,"min_size":18,"color":"#547b72","align":"center"}]})
    (folder/"customers.csv").write_text("姓名,编号\n今今,A001\n小星星,A002\n一位名字稍微长一点的客户,A003\n",encoding="utf-8-sig")
