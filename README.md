# iFinD 中继资金流向图生成脚本

这个仓库提供一个一键生成“收盘资金流向”长图的 Python 脚本，默认署名和水印为 `iFinD中继`。

脚本不会保存中继 key。请通过环境变量传入：

```powershell
$env:IFIND_RELAY_KEY="你的key"
python .\generate_ifind_relay_capital_flow.py --date 2026-05-21 --final-source ifind
```

也可以从已有 JSON 缓存重绘：

```powershell
python .\generate_ifind_relay_capital_flow.py --date 2026-05-21 --source-json .\.ifind_probe\xueqiu_style_capital_flow_v3.json
```

输出文件默认写入 `.ifind_probe/`：

- `ifind_relay_capital_flow_auto_YYYYMMDD.png`
- `ifind_relay_capital_flow_auto_YYYYMMDD.json`

## 安装依赖

```powershell
pip install -r requirements.txt
```

## 口径说明

当前中继可以获取板块/指数级实时资金流字段，也可以获取分钟行情字段；如果没有直接暴露分钟级大单净流入曲线，脚本会使用 `THS_HF` 分钟成交额和涨跌幅做代理曲线，并将最终标签锚定到资金流终值。

生成图仅用于数据整理展示，不作为买卖依据。

## 实时监控网页

启动本地监控服务：

```powershell
$env:IFIND_RELAY_KEY="你的key"
python .\ifind_relay_monitor.py --date 2026-05-22
```

然后打开：

```text
http://127.0.0.1:8765
```

默认会监听 `0.0.0.0:8765`。同一局域网里的其他设备可以用这台机器的局域网 IP 访问，例如 `http://192.168.x.x:8765`。

服务端默认会对 iFinD 中继做 5 秒节流，多开几个浏览器页面也不会让中继请求数成倍增加。后台采集线程会在没有网页访问时继续拉取，当天历史点会缓存到 `.ifind_probe/live_state_YYYYMMDD.json`，服务重启后可以续上。默认最多保留 10000 个点，足够覆盖完整交易日。

没有 key 或非交易时间调 UI 时，可以用模拟模式：

```powershell
python .\ifind_relay_monitor.py --mock --interval 5
```
