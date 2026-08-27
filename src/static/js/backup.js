/* ========================================================================= */
/* File: backup.js                                                           */
/* Role: Complete Management for Manual, Auto & Physical Backups (English)    */
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

        if (!manualRes.ok) throw new Error("Fetching manual backups failed.");
        if (!wgRes.ok) throw new Error("Fetching WireGuard backups failed.");
        if (!dbRes.ok) throw new Error("Fetching database backups failed.");

        const manualData = await manualRes.json();
        const wireguardData = await wgRes.json();
        const dbData = await dbRes.json();

        // 1. Manual Backups Table
        if (manualBackupList) {
            manualBackupList.innerHTML = manualData.backups && manualData.backups.length > 0
                ? manualData.backups.map(backup => `
                    <tr>
                        <td style="font-family:monospace;">${backup}</td>
                        <td style="text-align:center;">
                            <button class="btn btn-primary" style="padding:6px 12px; font-size:12px; margin:2px;" onclick="restoreBackup('${backup}', 'manual')"><i class="fas fa-rotate-left"></i> Restore</button>
                            <button class="btn btn-primary" style="padding:6px 12px; font-size:12px; margin:2px; background:#10b981; color:#000;" onclick="downloadBackup('${backup}')"><i class="fas fa-download"></i> Download</button>
                            <button class="btn btn-danger" style="padding:6px 12px; font-size:12px; margin:2px;" onclick="deleteBackup('${backup}', 'manual')"><i class="fas fa-trash-can"></i> Delete</button>
                        </td>
                    </tr>
                `).join("")
                : `<tr><td colspan="2" style="text-align:center; color:#8b949e;">No manual backups available.</td></tr>`;
        }

        // 2. WireGuard Auto Backups Table
        if (wireguardBackupList) {
            wireguardBackupList.innerHTML = wireguardData.backups && wireguardData.backups.length > 0
                ? wireguardData.backups.map(backup => `
                    <tr>
                        <td style="font-family:monospace;">${backup}</td>
                        <td style="text-align:center;">
                            <button class="btn btn-primary" style="padding:6px 12px; font-size:12px; margin:2px;" onclick="restoreBackup('${backup}', 'wireguard')"><i class="fas fa-rotate-left"></i> Restore</button>
                            <button class="btn btn-danger" style="padding:6px 12px; font-size:12px; margin:2px;" onclick="deleteBackup('${backup}', 'wireguard')"><i class="fas fa-trash-can"></i> Delete</button>
                        </td>
                    </tr>
                `).join("")
                : `<tr><td colspan="2" style="text-align:center; color:#8b949e;">No WireGuard backups available.</td></tr>`;
        }

        // 3. Database Auto Backups Table
        if (dbBackupList) {
            dbBackupList.innerHTML = dbData.backups && dbData.backups.length > 0
                ? dbData.backups.map(backup => `
                    <tr>
                        <td style="font-family:monospace;">${backup}</td>
                        <td style="text-align:center;">
                            <button class="btn btn-primary" style="padding:6px 12px; font-size:12px; margin:2px;" onclick="restoreBackup('${backup}', 'db')"><i class="fas fa-rotate-left"></i> Restore</button>
                            <button class="btn btn-danger" style="padding:6px 12px; font-size:12px; margin:2px;" onclick="deleteBackup('${backup}', 'db')"><i class="fas fa-trash-can"></i> Delete</button>
                        </td>
                    </tr>
                `).join("")
                : `<tr><td colspan="2" style="text-align:center; color:#8b949e;">No database backups available.</td></tr>`;
        }

    } catch (error) {
        console.error("Error fetching backups:", error);
        if (manualBackupList) manualBackupList.innerHTML = `<tr><td colspan="2" style="text-align:center; color:#ff4757;">Failed to load manual backups list.</td></tr>`;
        if (wireguardBackupList) wireguardBackupList.innerHTML = `<tr><td colspan="2" style="text-align:center; color:#ff4757;">Failed to load WireGuard backups list.</td></tr>`;
        if (dbBackupList) dbBackupList.innerHTML = `<tr><td colspan="2" style="text-align:center; color:#ff4757;">Failed to load database backups list.</td></tr>`;
    }
};

const deleteBackup = async (backupName, folder) => {
    showConfirm(`Are you sure you want to delete the backup "${backupName}"?`, async (confirmed) => {
        if (confirmed) {
            try {
                const folderParam = folder === "manual" ? "root" : folder;
                const response = await fetch(`/api/delete-backup?name=${encodeURIComponent(backupName)}&folder=${folderParam}`, { method: "DELETE" });
                const data = await response.json();
                
                if (response.ok) {
                    showAlert(data.message || "Backup deleted successfully.");
                    fetchBackups();
                } else {
                    showAlert(data.error || "Failed to delete backup.");
                }
            } catch (error) {
                console.error("Communication error:", error);
                showAlert("Error communicating with the server.");
            }
        }
    });
};

const restoreBackup = async (backupName, folder) => {
    const endpoint = folder === "manual" ? "/api/restore-backup" : "/api/restore-automated-backup";

    showConfirm(`Are you sure you want to restore "${backupName}"?\n(All current configurations will be overwritten)`, async (confirmed) => {
        if (confirmed) {
            try {
                const response = await fetch(endpoint, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ folder, backupName }),
                });
                const data = await response.json();
                
                if (response.ok) {
                    showAlert(data.message || "Backup restored successfully!");
                    fetchBackups(); 
                } else {
                    showAlert(data.error || "Failed to restore backup.");
                }
            } catch (error) {
                console.error("Restoration error:", error);
                showAlert("Error communicating with the server.");
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
            showConfirm("Are you sure you want to create a manual backup (.zip)?", async (confirmed) => {
                if (confirmed) {
                    try {
                        createBackupBtn.disabled = true;
                        createBackupBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating Backup...';
                        
                        const response = await fetch("/api/create-backup", { method: "POST" });
                        const data = await response.json();
                        
                        createBackupBtn.disabled = false;
                        createBackupBtn.innerHTML = '<i class="fas fa-plus-circle"></i> Create Manual Backup';
                        
                        if (response.ok) {
                            showAlert(data.message || "Backup created successfully!");
                            fetchBackups(); 
                        } else {
                            showAlert(data.error || "Failed to create backup.");
                        }
                    } catch (error) {
                        createBackupBtn.disabled = false;
                        createBackupBtn.innerHTML = '<i class="fas fa-plus-circle"></i> Create Manual Backup';
                        console.error("Backup creation error:", error);
                        showAlert("Error creating backup.");
                    }
                }
            });
        });
    }

    fetchBackups();
    setInterval(fetchBackups, 25000);
});