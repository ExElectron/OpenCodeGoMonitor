# -*- coding: utf-8 -*-
"""可交互图表组件（matplotlib 嵌入 PySide6）。

- 全部图表支持：缩放 / 框选 / 拖拽（内置 NavigationToolbar）
- 悬浮 Tooltip：悬停显示数值明细
- 点击回调：热力图/柱状图/散点图点击 → 联动底部明细表
"""
import datetime

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ocgmon.theme import chart_colors


class ChartWidget(QWidget):
    """一个自带工具栏的可交互图表容器。click_payload(str) 供外部联动。"""

    def __init__(self, click_handler=None, parent=None):
        super().__init__(parent)
        self.click_handler = click_handler
        self._tooltip_artist = None
        self._hover_fn = None
        self._canvas_click_map = None       # callable(xdata, ydata, event) -> payload or None

        self.fig = Figure(figsize=(7, 3.6), dpi=100, facecolor="none")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.toolbar.setStyleSheet("QToolBar { border: none; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.toolbar)
        lay.addWidget(self.canvas)

        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.fig.canvas.draw_idle()

    # ---------------- tooltip ----------------
    def set_hover(self, fn):
        """fn(xdata, ydata) -> str or None（悬停提示文本）"""
        self._hover_fn = fn

    def _on_motion(self, event):
        if event.inaxes is None or self._hover_fn is None:
            if self._tooltip_artist is not None:
                self._tooltip_artist.remove()
                self._tooltip_artist = None
                self.canvas.draw_idle()
            return
        text = self._hover_fn(event.xdata, event.ydata)
        if not text:
            return
        if self._tooltip_artist is None:
            self._tooltip_artist = event.inaxes.annotate(
                "", xy=(0, 0), xytext=(12, 12), textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.4", fc="#262931", ec="#363a45",
                          alpha=0.95, color="#e8eaf0"),
                arrowprops=dict(arrowstyle="-", color="#363a45"),
                zorder=100)
        self._tooltip_artist.xy = (event.xdata, event.ydata)
        self._tooltip_artist.set_text(text)
        self._tooltip_artist.set_visible(True)
        self.canvas.draw_idle()

    # ---------------- click linkage ----------------
    def set_click_map(self, fn):
        """fn(xdata, ydata, mouseevent) -> payload 或 None；非 None 时触发 click_handler(payload)"""
        self._canvas_click_map = fn

    def _on_press(self, event):
        if event.inaxes is None or self._canvas_click_map is None or event.button != 1:
            return
        try:
            payload = self._canvas_click_map(event.xdata, event.ydata, event)
        except Exception:
            return
        if payload is not None and self.click_handler:
            self.click_handler(payload)

    # ---------------- theme ----------------
    def apply_theme(self, p: dict):
        self.fig.patch.set_facecolor(p["bg"])
        for ax in self.fig.axes:
            ax.set_facecolor(p["panel"])
            for s in ax.spines.values():
                s.set_color(p["border"])
            ax.tick_params(colors=p["text_dim"])
            ax.xaxis.label.set_color(p["text"])
            ax.yaxis.label.set_color(p["text"])
            ax.title.set_color(p["text"])
            leg = ax.get_legend()
            if leg is not None:
                for t in leg.get_texts():
                    t.set_color(p["text"])
        self.canvas.draw_idle()


def fmt_money(v: float) -> str:
    return f"${v:,.4f}"


def fmt_int(v) -> str:
    return f"{int(v):,}"


# ===========================================================================
# 1) 模型占比环形图（总览）
# ===========================================================================
def build_donut(data: list, p: dict, click_handler=None) -> ChartWidget:
    """data: [{model, calls, tokens, cost}]"""
    w = ChartWidget(click_handler)
    c = chart_colors(p)
    ax = w.fig.add_subplot(111)
    total = sum(d["tokens"] for d in data)
    if total <= 0:
        ax.text(0.5, 0.5, "暂无数据", ha="center", va="center", color=c["dim"])
        ax.axis("off")
        w.apply_theme(p)
        return w
    labels = [d["model"] for d in data]
    sizes = [d["tokens"] for d in data]
    colors = [c["series"][i % len(c["series"])] for i in range(len(data))]
    wedges, _ = ax.pie(sizes, colors=colors, startangle=90, counterclock=False,
                       wedgeprops=dict(width=0.38, edgecolor=c["bg"], linewidth=2))
    # 中心文本
    ax.text(0, 0.08, "总Tokens", ha="center", va="center", fontsize=10, color=c["dim"])
    ax.text(0, -0.10, fmt_int(total), ha="center", va="center", fontsize=14,
            fontweight="bold", color=c["text"])
    ax.text(0.5, -1.18, "各模型 Token 用量占比（悬停查看详情，点击联动）",
            ha="center", transform=ax.transAxes, fontsize=9, color=c["dim"])
    # hover / click：扇形角度映射
    cum = np.cumsum(sizes).tolist()
    total_s = sum(sizes)

    def angle_to_index(angle_deg):
        a = (angle_deg - 90) % 360
        frac = (360 - a) % 360 / 360.0     # 逆时针
        pos = frac * total_s
        for i, cm in enumerate(cum):
            if pos <= cm:
                return i
        return len(sizes) - 1

    def hover(x, y):
        import math
        r = math.hypot(x, y)
        if not (0.38 <= r <= 1.0):
            return None
        idx = angle_to_index(math.degrees(math.atan2(y, x)))
        d = data[idx]
        pct = d["tokens"] / total * 100
        return (f"{d['model']}\n调用 {d['calls']:,} 次\nToken {d['tokens']:,}（{pct:.1f}%）\n"
                f"成本 {fmt_money(d['cost'])}")
    w.set_hover(hover)

    def click(x, y, ev):
        import math
        r = math.hypot(x, y)
        if 0.38 <= r <= 1.0:
            return data[angle_to_index(math.degrees(math.atan2(y, x)))]["model"]
        return None
    w.set_click_map(click)
    ax.set_aspect("equal")
    w.apply_theme(p)
    return w


# ===========================================================================
# 2) 双轴时间趋势（Token 左轴 + Cost 右轴）
# ===========================================================================
def build_dual_trend(data: list, granularity: str, p: dict, click_handler=None) -> ChartWidget:
    """data: [{bucket, ts_epoch, input_tokens, output_tokens, tokens, cost, calls}]"""
    w = ChartWidget(click_handler)
    c = chart_colors(p)
    fig = w.fig
    ax1 = fig.add_subplot(111)
    ax2 = ax1.twinx()
    if not data:
        ax1.text(0.5, 0.5, "暂无数据", ha="center", va="center", color=c["dim"])
        ax1.axis("off")
        w.apply_theme(p)
        return w
    xs = np.arange(len(data))
    labels = [d["bucket"][5:] for d in data]
    # 左轴：输入/输出 token 堆叠面积
    ax1.stackplot(xs, [d["input_tokens"] for d in data], [d["output_tokens"] for d in data],
                  labels=["输入Tokens", "输出Tokens"], colors=[c["accent"], c["accent2"]], alpha=0.85)
    ax1.set_ylabel("Tokens", color=c["dim"])
    ax1.ticklabel_format(axis="y", style="sci", scilimits=(6, 6))
    # 右轴：成本折线
    ax2.plot(xs, [d["cost"] for d in data], color=c["warn"], linewidth=2,
             marker="o", markersize=3, label="成本($)")
    ax2.set_ylabel("成本 ($)", color=c["warn"])
    ax2.tick_params(axis="y", colors=c["warn"])
    ax1.set_xticks(xs[::max(1, len(xs) // 10)])
    ax1.set_xticklabels(labels[::max(1, len(xs) // 10)], rotation=30, fontsize=8)
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=9, frameon=False)
    g = granularity or "day"

    def hover(x, y):
        i = int(round(x))
        if not (0 <= i < len(data)):
            return None
        d = data[i]
        return (f"{d['bucket']}\n输入 {fmt_int(d['input_tokens'])} | 输出 {fmt_int(d['output_tokens'])}\n"
                f"总Token {fmt_int(d['tokens'])} | 调用 {d['calls']:,} 次\n成本 {fmt_money(d['cost'])}")
    w.set_hover(hover)
    w.apply_theme(p)
    return w


# ===========================================================================
# 3) 星期×小时热力图
# ===========================================================================
WD_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def build_heatmap(matrix, max_calls, p: dict, click_handler=None) -> ChartWidget:
    """matrix: 7x24 调用次数。点击格点 → (weekday_index, hour)"""
    w = ChartWidget(click_handler)
    c = chart_colors(p)
    ax = w.fig.add_subplot(111)
    data = np.array(matrix, dtype=float)
    if data.sum() <= 0:
        ax.text(0.5, 0.5, "暂无数据", ha="center", va="center", color=c["dim"])
        ax.axis("off")
        w.apply_theme(p)
        return w
    norm = data / (max_calls or 1)
    im = ax.imshow(norm, cmap="YlOrRd" if p["bg"] == "#f4f6fa" else "magma",
                   aspect="auto", interpolation="nearest")
    ax.set_yticks(range(7), WD_LABELS, fontsize=9)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 2)], fontsize=8, rotation=0)
    ax.set_xlabel("小时（本地时间）")
    ax.set_ylabel("星期")
    ax.set_title("调用量热力图：星期 × 小时（点击格点联动明细）", fontsize=10)
    fig = w.fig
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.ax.tick_params(labelsize=8)
    cb.set_label("相对调用量", fontsize=8)

    def hover(x, y):
        hr, wd = int(np.floor(x)), int(np.floor(y))
        if not (0 <= hr < 24 and 0 <= wd < 7):
            return None
        v = matrix[wd][hr]
        return f"{WD_LABELS[wd]} {hr:02d}:00-{hr + 1:02d}:00\n调用 {v:,} 次"
    w.set_hover(hover)

    def click(x, y, ev):
        hr, wd = int(np.floor(x)), int(np.floor(y))
        if 0 <= hr < 24 and 0 <= wd < 7 and matrix[wd][hr] > 0:
            return {"kind": "heatmap", "weekday": wd, "hour": hr}
        return None
    w.set_click_map(click)
    w.apply_theme(p)
    return w


# ===========================================================================
# 4) 组合堆叠柱状图（API Key × 模型）
# ===========================================================================
def build_stacked_bar(keys: list, models: list, data, p: dict, click_handler=None) -> ChartWidget:
    """data: {key_id: {model: {calls, tokens, cost}}}。点击柱段 → {"kind":"stack", "key":..., "model":...}"""
    w = ChartWidget(click_handler)
    c = chart_colors(p)
    ax = w.fig.add_subplot(111)
    if not keys:
        ax.text(0.5, 0.5, "暂无数据", ha="center", va="center", color=c["dim"])
        ax.axis("off")
        w.apply_theme(p)
        return w
    x = np.arange(len(keys))
    bottoms = np.zeros(len(keys))
    patches = {}
    for mi, model in enumerate(models):
        vals = [data.get(k, {}).get(model, {}).get("tokens", 0) for k in keys]
        if sum(vals) == 0:
            continue
        color = c["series"][mi % len(c["series"])]
        bars = ax.bar(x, vals, bottom=bottoms, color=color, label=model,
                      edgecolor=c["bg"], linewidth=0.5, width=0.62)
        for bi, bar in enumerate(bars):
            patches[bar] = (keys[bi], model, vals[bi])
        bottoms += vals
    ax.set_xticks(x)
    ax.set_xticklabels([k[:12] + "…" if len(k) > 13 else k for k in keys], rotation=20, fontsize=8)
    ax.set_ylabel("Tokens")
    ax.ticklabel_format(axis="y", style="sci", scilimits=(6, 6))
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    ax.set_title("各 API Key × 模型 Token 消耗分布（点击柱段联动）", fontsize=10)

    def hover(x, y):
        for bar, (k, m, v) in patches.items():
            if bar.get_bbox().contains((x, y)):
                return f"{k}\n模型: {m}\nTokens: {fmt_int(v)}\n成本: {fmt_money(data[k][m].get('cost', 0))}"
        return None
    w.set_hover(hover)

    def click(x, y, ev):
        for bar, (k, m, v) in patches.items():
            if bar.get_bbox().contains((x, y)):
                return {"kind": "stack", "key": k, "model": m}
        return None
    w.set_click_map(click)
    w.apply_theme(p)
    return w


# ===========================================================================
# 5) 累积成本曲线 + 月底预测
# ===========================================================================
def build_cumulative(data: list, p: dict, click_handler=None) -> ChartWidget:
    """data: [{ts_epoch, cost, cum_cost}]。月底预测 = 当前速率 × 剩余天数。"""
    w = ChartWidget(click_handler)
    c = chart_colors(p)
    ax = w.fig.add_subplot(111)
    if not data:
        ax.text(0.5, 0.5, "暂无数据", ha="center", va="center", color=c["dim"])
        ax.axis("off")
        w.apply_theme(p)
        return w
    xs = np.array([d["ts_epoch"] for d in data], dtype=float)
    ys = np.array([d["cum_cost"] for d in data], dtype=float)
    ax.plot(xs, ys, color=c["accent"], linewidth=2.2, label="累积成本", zorder=3)
    ax.fill_between(xs, 0, ys, color=c["accent"], alpha=0.15)
    # 月底预测（虚线）
    now = datetime.datetime.now()
    last_day = datetime.datetime(now.year, now.month + 1, 1) - datetime.timedelta(days=1)
    last_epoch = int(last_day.replace(hour=23, minute=59).timestamp())
    if last_epoch > xs[-1] and ys[-1] > 0:
        days_elapsed = max((now.timestamp() - xs[0]) / 86400, 1e-6)
        rate = ys[-1] / days_elapsed
        forecast = ys[-1] + rate * (last_epoch - now.timestamp()) / 86400
        ax.plot([xs[-1], last_epoch], [ys[-1], forecast], color=c["warn"], linestyle="--",
                linewidth=2, label="月末预测", zorder=3)
        ax.annotate(f"月底预计 {fmt_money(forecast)}", xy=(last_epoch, forecast),
                    xytext=(last_epoch - (last_epoch - xs[0]) * 0.15, forecast),
                    fontsize=9, color=c["warn"],
                    arrowprops=dict(arrowstyle="->", color=c["warn"], lw=1))
    ax.set_ylabel("累积成本 ($)")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(
        lambda t, _: datetime.datetime.fromtimestamp(t).strftime("%m-%d")))
    ax.legend(fontsize=9, frameon=False)
    ax.set_title("累积成本曲线与月底预测", fontsize=10)

    def hover(x, y):
        i = int(np.argmin(np.abs(xs - x)))
        d = data[i]
        return (f"{datetime.datetime.fromtimestamp(d['ts_epoch']).strftime('%Y-%m-%d')}\n"
                f"当日成本 {fmt_money(d['cost'])} | 累积 {fmt_money(d['cum_cost'])}")
    w.set_hover(hover)
    w.apply_theme(p)
    return w


# ===========================================================================
# 6) 单次请求散点图（Token × Cost）
# ===========================================================================
def build_scatter(rows: list, p: dict, click_handler=None, sample_limit: int = 3000) -> ChartWidget:
    """rows: [{ts_epoch, total_tokens, cost, model_name, ...}]。点击点 → 该记录详情联动。"""
    w = ChartWidget(click_handler)
    c = chart_colors(p)
    ax = w.fig.add_subplot(111)
    if not rows:
        ax.text(0.5, 0.5, "暂无数据", ha="center", va="center", color=c["dim"])
        ax.axis("off")
        w.apply_theme(p)
        return w
    rows = rows[:sample_limit]
    xs = np.array([r["total_tokens"] for r in rows], dtype=float)
    ys = np.array([r["cost"] for r in rows], dtype=float)
    models = sorted({r["model_name"] for r in rows})
    model_idx = {m: i for i, m in enumerate(models)}
    # 计算异常线（3×均值）
    avg_cost = ys.mean() if len(ys) else 0
    avg_tokens = xs.mean() if len(xs) else 0
    pts = ax.scatter(xs, ys, c=[model_idx[r["model_name"]] for r in rows],
                     cmap="tab10", alpha=0.6, s=16, picker=True, zorder=3)
    ax.axhline(avg_cost * 3, color=c["danger"], linestyle="--", linewidth=1, alpha=0.8)
    ax.axvline(avg_tokens * 3, color=c["danger"], linestyle="--", linewidth=1, alpha=0.8)
    ax.text(1.01, 0.02, f"红线: 3×均值\n成本 {fmt_money(avg_cost * 3)}\nToken {fmt_int(avg_tokens * 3)}",
            transform=ax.transAxes, fontsize=8, color=c["dim"])
    ax.set_xscale("symlog", linthresh=100)
    ax.set_yscale("symlog", linthresh=0.001)
    ax.set_xlabel("单次请求总 Tokens")
    ax.set_ylabel("单次成本 ($)")
    ax.set_title("单次请求 Token × 成本 散点（右上角 = 异常高消耗）", fontsize=10)
    handles = [plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=c["series"][i % len(c["series"])],
                          markersize=7, label=m) for i, m in enumerate(models)]
    ax.legend(handles=handles, fontsize=8, frameon=False, loc="upper left")

    def hover(x, y):
        if x is None:
            return None
        # 找最近点
        i = int(np.argmin((xs - x) ** 2 + (ys - y) ** 2))
        r = rows[i]
        flag = " ⚠️异常" if (r["cost"] > avg_cost * 3 or r["total_tokens"] > avg_tokens * 3) else ""
        return (f"{r['model_name']}{flag}\nToken {fmt_int(r['total_tokens'])} | 成本 {fmt_money(r['cost'])}"
                f"\n{r['timestamp_local']}")
    w.set_hover(hover)

    def click(x, y, ev):
        if x is None:
            return None
        i = int(np.argmin((xs - x) ** 2 + (ys - y) ** 2))
        r = rows[i]
        return {"kind": "scatter", "record_id": r["id"]}
    w.set_click_map(click)
    w.apply_theme(p)
    return w
