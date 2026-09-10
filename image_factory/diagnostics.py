"""Registration/connection checks are not Photoshop rendering validation."""
import sys

def photoshop_environment():
    report={'platform':sys.platform,'registered':False,'render_verified':False}
    if sys.platform!='win32':
        report.update(status='unsupported_platform',message='Photoshop 桥接仅支持 Windows；图片与可视化编辑仍可用。')
        return report
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,r'Photoshop.Application\CLSID') as key:
            clsid=winreg.QueryValueEx(key,None)[0]
        report.update(registered=bool(clsid),status='registered_not_verified',message='检测到 Photoshop COM 注册；尚未验证 PSD 渲染。')
    except FileNotFoundError:
        report.update(status='not_registered',message='未检测到 Photoshop 自动化组件，无法做 PSD 实机验证。可继续使用 JSON 模板、贴膜和可视化编辑。')
    except OSError as e:
        report.update(status='check_failed',message='无法读取 Photoshop 注册信息：'+str(e))
    return report
