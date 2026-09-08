# Monitor service

The watchdog and the [alerts](alerts.md) run as their own systemd unit, **`parstanel-monitor.service`**, independently from any other process.

## Why it is separate

Monitoring depends on nothing but the machine being up, restarts itself if
it dies, and keeps working even if other services are stopped.

## Nothing to do by hand

It is installed automatically — the CLI installs it on launch and the updater
installs it as part of an update. [Health Check](health-check.md) reports if it
is not running.


<div dir="rtl">

## خلاصهٔ فارسی

واچ‌داگ و [هشدارها](alerts.md) در یک سرویس جداگانهٔ systemd به نام **`parstanel-monitor.service`** اجرا می‌شوند.

پایش به هیچ چیز جز روشن بودن سرور وابسته نیست و اگر متوقف شود خودش را دوباره بالا می‌آورد.
خودکار نصب می‌شود — هم موقع اجرای CLI و هم به‌عنوان بخشی از آپدیت.

</div>

[← Back to the docs index](README.md)
