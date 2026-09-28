"""
generate_load_test_charts.py — Генератор инфографики нагрузочного тестирования T-Invest.
"""

import matplotlib.pyplot as plt
import numpy as np

# Настройки стиля
plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
plt.rcParams["font.sans-serif"] = "DejaVu Sans"
plt.rcParams["font.size"] = 11

def plot_before_after():
    """Сравнение задержки (Latency p50 и p95) ДО и ПОСЛЕ Redis кэширования (100 юзеров)."""
    endpoints = [
        "Accounts List\n(ORM)",
        "Latest Snapshot\n(ORM Prefetch)",
        "Consolidated\nSnapshot (Map-Reduce)",
        "Risk Analytics\n(NumPy Metrics)",
        "Portfolio Chart\n(Matplotlib)",
    ]

    # Данные в миллисекундах (мс)
    p50_before = [46, 52, 340, 580, 18]
    p50_after = [5, 5, 4, 4, 3]

    p95_before = [84, 110, 630, 1100, 40]
    p95_after = [18, 20, 17, 24, 12]

    x = np.arange(len(endpoints))
    width = 0.35

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # График 1: Медиана (p50)
    bars1_b = ax1.bar(x - width/2, p50_before, width, label="ДО (Без кэша)", color="#e74c3c", alpha=0.85)
    bars1_a = ax1.bar(x + width/2, p50_after, width, label="ПОСЛЕ (Redis Cache)", color="#2ecc71", alpha=0.9)
    ax1.set_title("Медианное время отклика (p50, мс)\n(Меньше — лучше)", fontweight="bold", pad=12)
    ax1.set_ylabel("Миллисекунды (мс)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(endpoints)
    ax1.legend(loc="upper left")
    ax1.set_yscale("log")  # Логарифмическая шкала для наглядности колоссальной разницы
    ax1.grid(True, linestyle="--", alpha=0.5)

    # Добавляем текстовые аннотации ускорения
    speedups = ["9.2x", "10.4x", "85x", "145x", "6x"]
    for i, s in enumerate(speedups):
        ax1.annotate(
            f"⚡ {s}",
            (x[i] + width/2, p50_after[i]),
            textcoords="offset points",
            xytext=(0, 6),
            ha="center",
            fontweight="bold",
            color="#27ae60",
            fontsize=10
        )

    # График 2: 95-й перцентиль (p95)
    bars2_b = ax2.bar(x - width/2, p95_before, width, label="ДО (Без кэша)", color="#e67e22", alpha=0.85)
    bars2_a = ax2.bar(x + width/2, p95_after, width, label="ПОСЛЕ (Redis Cache)", color="#3498db", alpha=0.9)
    ax2.set_title("95-й перцентиль задержки (p95, мс)\n(Худшие 5% запросов)", fontweight="bold", pad=12)
    ax2.set_ylabel("Миллисекунды (мс)")
    ax2.set_xticks(x)
    ax2.set_xticklabels(endpoints)
    ax2.legend(loc="upper left")
    ax2.set_yscale("log")
    ax2.grid(True, linestyle="--", alpha=0.5)

    fig.suptitle("T-Invest Portfolio Auditor: Результаты оптимизации Redis Cache-Aside", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    plt.savefig("docs/assets/load_test_latency_comparison.png", dpi=300, bbox_inches="tight")
    plt.close()
    print("Saved docs/assets/load_test_latency_comparison.png")


def plot_stress_limits():
    """Стресс-тестирование: Dev-сервер vs Продакшн Gunicorn (1000 клиентов)."""
    stages = [
        "100 Users\n(Штатный трафик)",
        "500 Users\n(Шквал DevServer)",
        "1 000 Users\n(DevServer: Сбой)",
        "1 000 Users\n(Gunicorn 4W: Успех)",
    ]

    rps = [86.7, 173.0, 117.3, 563.3]
    error_rate = [0.0, 0.0, 41.01, 0.0]

    fig, ax1 = plt.subplots(figsize=(12, 6))

    colors = ["#2980b9", "#2980b9", "#7f8c8d", "#27ae60"]
    ax1.set_xlabel("Архитектурная конфигурация и нагрузка", fontweight="bold", labelpad=10)
    ax1.set_ylabel("Пропускная способность (RPS, Запросов/сек)", color="#2c3e50", fontweight="bold")
    bars = ax1.bar(stages, rps, color=colors, width=0.45, alpha=0.85, label="RPS (Запросов/сек)")
    ax1.tick_params(axis="y", labelcolor="#2c3e50")
    ax1.set_ylim(0, 680)

    for bar in bars:
        h = bar.get_height()
        ax1.annotate(f"{h:.1f} req/s",
                     (bar.get_x() + bar.get_width() / 2, h),
                     textcoords="offset points", xytext=(0, 6),
                     ha="center", fontweight="bold", color="#2c3e50", fontsize=10)

    # Вторая ось Y для % ошибок
    ax2 = ax1.twinx()
    color2 = "#c0392b"
    ax2.set_ylabel("Доля ошибок (% Fails)", color=color2, fontweight="bold")
    line = ax2.plot(stages, error_rate, color=color2, marker="o", linewidth=3, markersize=8, label="% Ошибок")
    ax2.tick_params(axis="y", labelcolor=color2)
    ax2.set_ylim(-3, 55)

    annotations = ["0% (OK)", "0% (OK)", "41.0% (Broken Pipe)", "0.0% (Решено!)"]
    for i, txt in enumerate(annotations):
        c = "#c0392b" if "Broken" in txt else "#27ae60"
        ax2.annotate(txt,
                     (stages[i], error_rate[i]),
                     textcoords="offset points", xytext=(0, 10),
                     ha="center", fontweight="bold", color=c)

    plt.title("Эволюция масштабируемости: DevServer (Broken Pipe) -> Gunicorn 4 Workers (563 RPS, 0% Fails)", fontweight="bold", pad=15)
    plt.tight_layout()
    plt.savefig("docs/assets/load_test_stress_limits.png", dpi=300, bbox_inches="tight")
    plt.close()
    print("Saved docs/assets/load_test_stress_limits.png")


if __name__ == "__main__":
    plot_before_after()
    plot_stress_limits()
