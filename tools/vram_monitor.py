import time
from pynvml import *
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn

def get_vram_info():
    nvmlInit()
    handle = nvmlDeviceGetHandleByIndex(0)
    info = nvmlDeviceGetMemoryInfo(handle)
    # Convert bytes to MiB
    used = info.used / (1024**2)
    total = info.total / (1024**2)
    nvmlShutdown()
    return used, total

def run_monitor():
    progress = Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("[bold white]{task.completed:.0f} / {task.total:.0f} MiB"),
        TextColumn("[bold yellow]({task.percentage:>3.0f}%)"),
    )
    
    used, total = get_vram_info()
    task_id = progress.add_task("RTX 5050 VRAM", total=total)

    with Live(Panel(progress, title="IRIS Performance Monitor", border_style="cyan"), refresh_per_second=2):
        while True:
            used, _ = get_vram_info()
            progress.update(task_id, completed=used)
            
            # Color coding for safety
            if (used / total) > 0.90:
                progress.columns[1].pulse = True # Pulsate if > 90%
            else:
                progress.columns[1].pulse = False
                
            time.sleep(0.5)

if __name__ == "__main__":
    try:
        run_monitor()
    except KeyboardInterrupt:
        print("\nMonitor closed.")