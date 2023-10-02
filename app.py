from io import BytesIO
import flask
import requests
import time
import qrcode
import loguru
import base64
from barcode import EAN13
from barcode.writer import ImageWriter
from barcode.base import Barcode
import yaml

# 学号
username = ""
# base64 编码的密码
pwd = ""

Barcode.default_writer_options['write_text'] = False
Barcode.default_writer_options['quiet_zone'] = 0

logging = loguru.logger


def notify_feishu(msg):
    webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/ade4ea5a-a64c-40bf-9391-c42c837a421a"
    msg_template = {
        "msg_type": "text",
        "content": {
            "text": msg
        }
    }
    requests.post(webhook_url, json=msg_template)


logging.add(notify_feishu, format="{level} {message}", level="WARNING")
logging.add("logs/{time}.log")

ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
url = "https://pay.xjtu.edu.cn/"

session = requests.session()

authCode = ""

logging.info("程序启动")


def getTime():
    return str(int(time.time() * 1000))


def login():
    try:
        session = requests.session()
        session.get("https://org.xjtu.edu.cn/openplatform/oauth/authorize?appId=1597&redirectUri=https://pay.xjtu.edu.cn/ThirdWeb/CasQrcode&responseType=code&scope=user_info&state=1234")
        data = session.post(
            'https://org.xjtu.edu.cn/openplatform/g/admin/login',
            json={
                "jcaptchaCode": "",
                "loginType": 1,
                "pwd": pwd,
                "username": username
            },
            timeout=30
        ).json()['data']
        session.cookies.set('open_Platform_User', str(data['tokenKey']))
        x = session.get(
            "https://org.xjtu.edu.cn/openplatform/oauth/auth/getRedirectUrl?userType=1&personNo="+username+"&_="+getTime())
        url = x.json()['data']
        web = session.get(url)
        authCode = web.text.split("sessionStorage.Authorization = '")[
            1].split("'")[0]
        session.post("https://pay.xjtu.edu.cn/ThirdWeb/VoucherList", headers={
            "Authorization": authCode
        })
        return authCode
    except Exception as e:
        logging.error(f"登录时发生错误: {e}")
        return None


def getPayCode():
    try:
        x = session.post("https://pay.xjtu.edu.cn/ThirdWeb/GetBarCode", headers={
            "Authorization": authCode,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
        }, data={
            "acctype": "000"
        })
        return x.json()
    except Exception as e:
        logging.error(f"Error getting pay code: {e}")
        return None


flask_app = flask.Flask(__name__)
logging.info("尝试登录中")
authCode = login()
try_count = 0
while(authCode == None):
    logging.warning("登录失败，尝试重新登录，次数: " + str(try_count+1))
    authCode = login()
    try_count += 1
    if(try_count > 5):
        logging.error("登录失败，程序退出")
        while(True):
            pass
logging.info("登录成功")


@flask_app.route('/getPayCode')
def getHTTPPayCode():
    global authCode
    try:
        # 获取访问者IP
        ip = flask.request.remote_addr
        logging.info(f"IP: {ip} 尝试获取付款码")
        res = getPayCode()
        if(res['Obj2']):
            logging.info("登录过期，重新登录")
            authCode = login()
            res = getPayCode()
        image = qrcode.make(res['Obj'][0])
        byte_io = BytesIO()
        image.save(byte_io, 'PNG')
        byte_io.seek(0)
        return flask.send_file(byte_io, mimetype='image/png')
    except Exception as e:
        logging.error(f"Error in index route: {e}")
        return flask.Response("Error", status=500)


class NoTextSVGWriter(ImageWriter):
    def _paint_text(self, xpos, ypos):
        pass  # Do nothing, don't paint text


@flask_app.route('/')
def index():
    global authCode
    try:
        # 获取访问者IP
        ip = flask.request.remote_addr
        logging.info(f"IP: {ip} 尝试获取付款码")
        res = getPayCode()
        if(res['Obj2']):
            logging.info("登录过期，重新登录")
            authCode = login()
            res = getPayCode()
        pay_number = res['Obj'][0]

        bar_writer = NoTextSVGWriter()
        bar_code = EAN13(pay_number, writer=bar_writer)
        bar_code_bytes = BytesIO()
        bar_code.write(bar_code_bytes)
        bar_code_bytes = bar_code_bytes.getvalue()
        bar_code_base64_str = base64.b64encode(bar_code_bytes).decode()

        qrcode_image = qrcode.make(pay_number, border=0)
        image_bytes = BytesIO()
        qrcode_image.save(image_bytes, format='PNG')
        image_bytes = image_bytes.getvalue()
        image_base64_str = base64.b64encode(image_bytes).decode()

        pay_number_str = pay_number[0:4]+'*'*(len(pay_number)-8)

        return flask.render_template('index.html', bar_code_base=bar_code_base64_str, pay_number=pay_number_str, qrcode_base=image_base64_str)
    except Exception as e:
        logging.error(f"Error in index route: {e}")
        exit()
        return flask.Response("Error", status=500)


@flask_app.route('/files/<path:filename>')
def send_file(filename):
    return flask.send_from_directory(flask_app.static_folder, filename)


if __name__ == '__main__':
    try:
        flask_app.run()
    except Exception as e:
        logging.error(f"启动 Flask 应用失败: {e}")
