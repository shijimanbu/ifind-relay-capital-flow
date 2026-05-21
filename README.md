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

