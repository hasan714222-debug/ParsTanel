/* ========================================================================= */
/* نام فایل: settings-fa.js                                                 */
/* نقش: مدیریت کامل تنظیمات سیستم، وب‌سرور و وایرگارد (نسخه فارسی)            */
/* ========================================================================= */

async function loadSettings() {
    try {
        // ۱. دریافت تنظیمات وب‌سرور Flask
        const flaskResponse = await fetch('/api/flask-config');
        if (!flaskResponse.ok) throw new Error("دریافت تنظیمات وب‌سرور با خطا مواجه شد.");
        const flaskConfig = await flaskResponse.json();
        
        const webPortInput = document.getElementById('webPort');
        const enableTlsSelect = document.getElementById('enableTLS');
        const certPathInput = document.getElementById('certPath');
        const keyPathInput = document.getElementById('keyPath');

        if (webPortInput) webPortInput.value = flaskConfig.port || '';
        if (enableTlsSelect) {
            enableTlsSelect.value = flaskConfig.tls ? "true" : "false";
            enableTlsSelect.dispatchEvent(new Event('change'));
        }
        if (certPathInput && flaskConfig.cert_path) certPathInput.value = flaskConfig.cert_path;
        if (keyPathInput && flaskConfig.key_path) keyPathInput.value = flaskConfig.key_path;

        // ۲. دریافت اطلاعات کاربر
        const userResponse = await fetch('/api/user-info');
        if (!userResponse.ok) throw new Error("دریافت اطلاعات کاربر با خطا مواجه شد.");
        const userInfo = await userResponse.json();
        const usernameInput = document.getElementById('newUsername');
        if (usernameInput) usernameInput.value = userInfo.username || '';

        // ۳. دریافت لیست اینترفیس‌های وایرگارد
        const wgResponse = await fetch('/api/configs');
        if (!wgResponse.ok) throw new Error("دریافت کانفیگ‌های وایرگارد با خطا مواجه شد.");
        const wgConfigs = await wgResponse.json();
        const configSelect = document.getElementById('wgConfigSelect');

        if (configSelect && wgConfigs.configs) {
            configSelect.innerHTML = "";
            wgConfigs.configs.forEach(config => {
                const option = document.createElement('option');
                option.value = config;
                option.textContent = config;
                configSelect.appendChild(option);
            });

            if (wgConfigs.configs.length > 0) {
                configSelect.value = wgConfigs.configs[0];
                await loadWGDetails(wgConfigs.configs[0]);
            }

            configSelect.addEventListener('change', (event) => {
                loadWGDetails(event.target.value);
            });
        }
    } catch (error) {
        console.error('خطا در بارگذاری تنظیمات:', error);
        showAlert(`خطا در بارگذاری تنظیمات: ${error.message}`);
    }
}

async function loadWGDetails(configName) {
    try {
        const response = await fetch(`/api/config-details?config=${encodeURIComponent(configName)}`);
        if (!response.ok) throw new Error("دریافت جزئیات کانفیگ وایرگارد ناموفق بود.");
        const details = await response.json();

        const portInput = document.getElementById('wgPort');
        const mtuInput = document.getElementById('wgMTU');
        const dnsInput = document.getElementById('wgDNS');

        if (portInput) portInput.value = details.ListenPort || '';
        if (mtuInput) mtuInput.value = details.MTU || '';
        if (dnsInput) dnsInput.value = details.DNS || '';
    } catch (error) {
        console.error('خطا در دریافت جزئیات وایرگارد:', error);
    }
}

async function loadCustomIp() {
    try {
        const response = await fetch('/api/get-custom-ip');
        if (!response.ok) throw new Error("دریافت آی‌پی اختصاصی با خطا مواجه شد.");
        const data = await response.json();
        const customIpInput = document.getElementById('customIp');
        if (customIpInput) customIpInput.value = data.custom_ip || '';
    } catch (error) {
        console.error('خطا در بارگذاری آی‌پی اختصاصی:', error);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // تب‌های ناوبری
    const tabs = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(btn => btn.classList.remove('active'));
            tabContents.forEach(content => content.classList.remove('active'));

            tab.classList.add('active');
            const targetContent = document.getElementById(tab.dataset.tab);
            if (targetContent) targetContent.classList.add('active');
        });
    });

    // کنترل نمایش فیلدهای گواهی SSL
    const tlsSelect = document.getElementById('enableTLS');
    const tlsDependentFields = document.querySelectorAll('.tls-dependent');
    if (tlsSelect) {
        tlsSelect.addEventListener('change', () => {
            const isTLS = tlsSelect.value === 'true';
            tlsDependentFields.forEach(field => {
                field.style.display = isTLS ? 'block' : 'none';
            });
        });
    }

    // هدرهای آکاردئونی
    const collapsibleHeaders = document.querySelectorAll('.collapsible-header');
    collapsibleHeaders.forEach(header => {
        header.addEventListener('click', () => {
            const container = header.parentElement;
            if (container) container.classList.toggle('active');
        });
    });

    // ثبت فرم تغییر مشخصات کاربر
    const userForm = document.getElementById('updateUserForm');
    if (userForm) {
        userForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            try {
                const username = document.getElementById('newUsername').value.trim();
                const password = document.getElementById('newPassword').value;

                if (!username || !password) {
                    showAlert("نام کاربری و کلمه عبور هر دو الزامی هستند.");
                    return;
                }

                const response = await fetch('/api/update-user', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || result.message || "خطا در تغییر اطلاعات کاربری.");
                showAlert(result.message || "اطلاعات کاربری با موفقیت به‌روزرسانی شد!");
            } catch (error) {
                console.error('خطا در به‌روزرسانی کاربر:', error);
                showAlert(`خطا: ${error.message}`);
            }
        });
    }

    // ثبت فرم تنظیمات Flask
    const flaskForm = document.getElementById('updateFlaskForm');
    if (flaskForm) {
        flaskForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            try {
                const port = parseInt(document.getElementById('webPort').value, 10);
                const tls = document.getElementById('enableTLS').value === 'true';
                const certPath = document.getElementById('certPath').value.trim();
                const keyPath = document.getElementById('keyPath').value.trim();

                if (isNaN(port) || port < 1 || port > 65535) {
                    showAlert("پورت باید عددی معتبر بین 1 تا 65535 باشد.");
                    return;
                }

                if (tls && (!certPath || !keyPath)) {
                    showAlert("در صورت فعال بودن TLS، وارد کردن مسیر Cert و Key الزامی است.");
                    return;
                }

                const requestBody = { port: port, tls: tls, cert_path: certPath, key_path: keyPath };

                const response = await fetch('/api/update-flask-config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestBody)
                });

                const result = await response.json();
                if (!response.ok) throw new Error(result.error || result.message || "خطا در ذخیره تنظیمات Flask.");
                showAlert(result.message || "تنظیمات وب‌سرور با موفقیت ذخیره شد!");
            } catch (error) {
                console.error('خطای ذخیره وب‌سرور:', error);
                showAlert(`خطا در تنظیمات وب‌سرور: ${error.message}`);
            }
        });
    }

    // ثبت فرم تنظیمات کانفیگ وایرگارد
    const wgForm = document.getElementById('updateWGForm');
    if (wgForm) {
        wgForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            try {
                const config = document.getElementById('wgConfigSelect').value;
                const port = document.getElementById('wgPort').value ? parseInt(document.getElementById('wgPort').value, 10) : null;
                const mtu = document.getElementById('wgMTU').value ? parseInt(document.getElementById('wgMTU').value, 10) : null;
                const dns = document.getElementById('wgDNS').value.trim() || null;

                const response = await fetch('/api/update-wireguard-config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ config, port, mtu, dns })
                });

                const result = await response.json();
                if (!response.ok) throw new Error(result.error || result.message || "خطا در به‌روزرسانی کانفیگ وایرگارد.");
                showAlert(result.message || "کانفیگ وایرگارد با موفقیت به‌روزرسانی شد!");
            } catch (error) {
                console.error('خطای وایرگارد:', error);
                showAlert(`خطا در کانفیگ وایرگارد: ${error.message}`);
            }
        });
    }

    // ثبت فرم آی‌پی / ساب‌دامین اختصاصی
    const customIpForm = document.getElementById('updateCustomIpForm');
    if (customIpForm) {
        customIpForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const customIp = document.getElementById('customIp').value.trim();
            if (!customIp) {
                showAlert("وارد کردن آی‌پی یا ساب‌دامین الزامی است.");
                return;
            }

            try {
                const response = await fetch('/api/update-custom-ip', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ custom_ip: customIp })
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || result.message || "خطا در ذخیره آی‌پی اختصاصی.");
                showAlert(result.message || "آی‌پی یا ساب‌دامین با موفقیت ثبت شد!");
                loadCustomIp();
            } catch (error) {
                console.error('خطای آی‌پی اختصاصی:', error);
                showAlert(`خطا: ${error.message}`);
            }
        });
    }

    // بارگذاری اولیه مقادیر
    loadCustomIp();
    loadSettings();
});

function showAlert(message) {
    const alertModal = document.getElementById("alertModal");
    const alertMessage = document.getElementById("alertMessage");

    if (!alertModal || !alertMessage) {
        alert(message);
        return;
    }

    alertMessage.textContent = message;
    alertModal.style.display = "flex";

    setTimeout(() => {
        alertModal.style.display = "none";
    }, 3500); 
}

function showConfirm(message, callback) {
    const confirmModal = document.getElementById("confirmModal");
    const confirmMessage = document.getElementById("confirmMessage");
    const confirmYes = document.getElementById("confirmYes");
    const confirmNo = document.getElementById("confirmNo");

    if (!confirmModal || !confirmMessage || !confirmYes || !confirmNo) {
        const result = confirm(message);
        if (typeof callback === "function") callback(result);
        return;
    }

    confirmMessage.textContent = message;
    confirmModal.style.display = "flex";

    const safeCallback = typeof callback === "function" ? callback : () => {};

    confirmYes.onclick = () => {
        confirmModal.style.display = "none";
        safeCallback(true); 
    };

    confirmNo.onclick = () => {
        confirmModal.style.display = "none";
        safeCallback(false); 
    };
}