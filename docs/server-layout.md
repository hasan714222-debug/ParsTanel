# Server layout (file locations)

Everything lives in a tidy, predictable layout. You can also see this any time
from **Manage → File Locations** in the CLI.

| Path | What |
|------|------|
| `/root/ParsTanel` | The release bundle and downloaded archives. |
| `/root/ParsTanel/backups` | [Backup](backup-restore.md) `.tar.gz` files. |
| `/etc/parstanel` | Tunnel configs (one `.toml` per tunnel) and runtime state. |
| `/usr/local/bin/parstanel` | The binary itself. |
| `parstanel-<name>.service` | A systemd unit per tunnel. |
| `parstanel-monitor.service` | The [monitor service](monitor-service.md). |

The install directory is recorded in `/etc/parstanel/install_path`, which is what
the uninstaller reads to know what to remove.


<div dir="rtl">

## خلاصهٔ فارسی

همه‌چیز در یک ساختار مرتب و قابل‌پیش‌بینی است. همین را هر وقت خواستی از
`Manage → File Locations` در منوی CLI هم می‌بینی.

`‎/root/ParsTanel` بستهٔ ریلیز و آرشیوهای دانلودشده ·
`‎/root/ParsTanel/backups` فایل‌های [پشتیبان](backup-restore.md) ·
`‎/etc/parstanel` کانفیگ تونل‌ها (برای هر تونل یک فایل `.toml`) و وضعیت اجرا ·
`‎/usr/local/bin/parstanel` خودِ باینری ·
`parstanel-<name>.service` یک یونیت systemd به‌ازای هر تونل ·
`parstanel-monitor.service` [سرویس مانیتور](monitor-service.md).

مسیر نصب در `/etc/parstanel/install_path` ثبت می‌شود و حذف‌کنندهٔ داخلی از روی
همان می‌فهمد چه چیزی را پاک کند.

</div>

[← Back to the docs index](README.md)
