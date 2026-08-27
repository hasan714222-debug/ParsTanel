/* ========================================================================= */
/* نام فایل: backup-fa.js                                                   */
/* نقش: مدیریت کامل بکاپ‌های دستی، خودکار و بازیابی فیزیکی (نسخه فارسی)     */
/* ========================================================================= */

const fetchBackups = async () => {
    const manualBackupList = document.querySelector("#manualBackupList tbody");
    const wireguardBackupList = document.querySelector("#wireguardBackupList tbody");
    const dbBackupList = document.querySelector("#dbBackupList tbody");

    try {
        const [manualRes, wgRes, dbRes] = await Promise.all([
            fetch("/api/backups"),
            fetch("/api/auto-backups?folder=wireguard"),
            fetch("/api/auto-backups?folder=db")
        ]);

        if (!manualRes.ok) throw new Error("دریافت پشتیبان‌های دستی ناموفق بود.");
        if (!wgRes.ok) throw new Error("دریافت پشتیبان‌های وایرگارد ناموفق بود.");
        if (!dbRes.ok) throw new Error("دریافت پشتیبان‌های دیتابیس ناموفق بود.");

        const manualData = await manualRes.json();
        const wireguardData = await wgRes.json();
        const dbData = await dbRes.json();

        // ۱. جدول بکاپ‌های دستی
        if (manualBackupList) {
            manualBackupList.innerHTML = manualData.backups && manualData.backups.length > 0
                ? manualData.backups.map(backup => `
                    <tr>
                        <td style="font-family:monospace; direction:ltr; text-align:left;">${backup}</td>
                        <td style="text-align:center;">
                            <button class="btn btn-primary" style="padding:6px 12px; font-size:12px; margin:2px;" onclick="restoreBackup('${backup}', 'manual')"><i class="fas fa-rotate-left"></i> بازیابی</button>
                            <button class="btn btn-primary" style="padding:6px 12px; font-size:12px; margin:2px; background:#10b981; color:#000;" onclick="downloadBackup('${backup}')"><i class="fas fa-download"></i> دانلود</button>
                            <button class="btn btn-danger" style="padding:6px 12px; font-size:12px; margin:2px;" onclick="deleteBackup('${backup}', 'manual')"><i class="fas fa-trash-can"></i> حذف</button>
                        </td>
                    </tr>
                `).join("")
                : `<tr><td colspan="2" style="text-align:center; color:#8b949e;">پشتیبان دستی یافت نشد.</td></tr>`;
        }

        // ۲. جدول بکاپ‌های خودکار وایرگارد
        if (wireguardBackupList) {
            wireguardBackupList.innerHTML = wireguardData.backups && wireguardData.backups.length > 0
                ? wireguardData.backups.map(backup => `
                    <tr>
                        <td style="font-family:monospace; direction:ltr; text-align:left;">${backup}</td>
                        <td style="text-align:center;">
                            <button class="btn btn-primary" style="padding:6px 12px; font-size:12px; margin:2px;" onclick="restoreBackup('${backup}', 'wireguard')"><i class="fas fa-rotate-left"></i> بازیابی</button>
                            <button class="btn btn-danger" style="padding:6px 12px; font-size:12px; margin:2px;" onclick="deleteBackup('${backup}', 'wireguard')"><i class="fas fa-trash-can"></i> حذف</button>
                        </td>
                    </tr>
                `).join("")
                : `<tr><td colspan="2" style="text-align:center; color:#8b949e;">پشتیبان خودکار وایرگارد یافت نشد.</td></tr>`;
        }

        // ۳. جدول بکاپ‌های دیتابیس
        if (dbBackupList) {
            dbBackupList.innerHTML = dbData.backups && dbData.backups.length > 0
                ? dbData.backups.map(backup => `
                    <tr>
                        <td style="font-family:monospace; direction:ltr; text-align:left;">${backup}</td>
                        <td style="text-align:center;">
                            <button class="btn btn-primary" style="padding:6px 12px; font-size:12px; margin:2px;" onclick="restoreBackup('${backup}', 'db')"><i class="fas fa-rotate-left"></i> بازیابی</button>
                            <button class="btn btn-danger" style="padding:6px 12px; font-size:12px; margin:2px;" onclick="deleteBackup('${backup}', 'db')"><i class="fas fa-trash-can"></i> حذف</button>
                        </td>
                    </tr>
                `).join("")
                : `<tr><td colspan="2" style="text-align:center; color:#8b949e;">پشتیبان خودکار دیتابیس یافت نشد.</td></tr>`;
        }

    } catch (error) {
        console.error("خطا در بارگذاری پشتیبان‌ها:", error);
        if (manualBackupList) manualBackupList.innerHTML = `<tr><td colspan="2" style="text-align:center; color:#ff4757;">خطا در دریافت لیست پشتیبان‌های دستی.</td></tr>`;
        if (wireguardBackupList) wireguardBackupList.innerHTML = `<tr><td colspan="2" style="text-align:center; color:#ff4757;">خطا در دریافت لیست پشتیبان‌های وایرگارد.</td></tr>`;
        if (dbBackupList) dbBackupList.innerHTML = `<tr><td colspan="2" style="text-align:center; color:#ff4757;">خطا در دریافت لیست پشتیبان‌های دیتابیس.</td></tr>`;
    }
};

const deleteBackup = async (backupName, folder) => {
    showConfirm(`آیا از حذف دائم فایل پشتیبان "${backupName}" اطمینان دارید؟`, async (confirmed) => {
        if (confirmed) {
            try {
                const folderParam = folder === "manual" ? "root" : folder;
                const response = await fetch(`/api/delete-backup?name=${encodeURIComponent(backupName)}&folder=${folderParam}`, { method: "DELETE" });
                const data = await response.json();
                
                if (response.ok) {
                    showAlert(data.message || "فایل پشتیبان با موفقیت حذف شد.");
                    fetchBackups();
                } else {
                    showAlert(data.error || "خطا در حذف فایل پشتیبان.");
                }
            } catch (error) {
                console.error("خطای ارتباط:", error);
                showAlert("خطا در برقراری ارتباط با سرور.");
            }
        }
    });
};

const restoreBackup = async (backupName, folder) => {
    const endpoint = folder === "manual" ? "/api/restore-backup" : "/api/restore-automated-backup";

    showConfirm(`آیا از بازیابی پشتیبان "${backupName}" اطمینان دارید؟\n(تمام اطلاعات با این نسخه جایگزین خواهد شد)`, async (confirmed) => {
        if (confirmed) {
            try {
                const response = await fetch(endpoint, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ folder, backupName }),
                });
                const data = await response.json();
                
                if (response.ok) {
                    showAlert(data.message || "پشتیبان با موفقیت بازیابی شد!");
                    fetchBackups(); 
                } else {
                    showAlert(data.error || "خطا در بازیابی پشتیبان.");
                }
            } catch (error) {
                console.error("خطای بازیابی:", error);
                showAlert("خطا در برقراری ارتباط با سرور.");
            }
        }
    });
};

const downloadBackup = (backupName) => {
    window.open(`/api/download-backup?name=${encodeURIComponent(backupName)}`, "_blank");
};

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

document.addEventListener("DOMContentLoaded", () => {
    const createBackupBtn = document.getElementById("createBackupBtn");

    if (createBackupBtn) {
        createBackupBtn.addEventListener("click", async () => {
            showConfirm("آیا می‌خواهید یک فایل پشتیبان دستی کامل (.zip) ایجاد کنید؟", async (confirmed) => {
                if (confirmed) {
                    try {
                        createBackupBtn.disabled = true;
                        createBackupBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> در حال ساخت بکاپ...';
                        
                        const response = await fetch("/api/create-backup", { method: "POST" });
                        const data = await response.json();
                        
                        createBackupBtn.disabled = false;
                        createBackupBtn.innerHTML = '<i class="fas fa-plus-circle"></i> ساخت فایل پشتیبانی';
                        
                        if (response.ok) {
                            showAlert(data.message || "فایل پشتیبان با موفقیت ایجاد شد!");
                            fetchBackups(); 
                        } else {
                            showAlert(data.error || "خطا در ایجاد فایل پشتیبان.");
                        }
                    } catch (error) {
                        createBackupBtn.disabled = false;
                        createBackupBtn.innerHTML = '<i class="fas fa-plus-circle"></i> ساخت فایل پشتیبانی';
                        console.error("خطای ساخت بکاپ:", error);
                        showAlert("خطا در ایجاد فایل پشتیبان.");
                    }
                }
            });
        });
    }

    fetchBackups();
    setInterval(fetchBackups, 25000);
});