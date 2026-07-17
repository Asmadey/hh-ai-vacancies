// ==UserScript==
// @name         HH.ru Auto Response
// @namespace    http://tampermonkey.net/
// @version      1.1
// @description  Автоотклик на вакансии hh.ru с cover letter из Google Sheets
// @author       Vlad
// @match        https://hh.ru/vacancy/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @connect      docs.google.com
// @connect      sheets.googleapis.com
// @connect      hh.ru
// ==/UserScript==

(function() {
    'use strict';

    // === CONFIG: replace with your values ===
    const SPREADSHEET_ID = 'YOUR_SPREADSHEET_ID';
    const SHEET_GID = 'YOUR_SHEET_GID';
    const DEFAULT_RESUME_HASH = 'YOUR_RESUME_HASH';
    // ========================================

    function getXsrf() {
        const match = document.cookie.match(/_xsrf=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : null;
    }

    function getVacancyId() {
        const match = location.pathname.match(/\/vacancy\/(\d+)/);
        return match ? match[1] : null;
    }

    function getResumeHash() {
        let hash = localStorage.getItem('LastOpenedResume');
        if (!hash) hash = GM_getValue('hh_resume_hash', null);
        if (!hash) {
            hash = DEFAULT_RESUME_HASH;
            if (hash && hash !== 'YOUR_RESUME_HASH') {
                GM_setValue('hh_resume_hash', hash);
            }
        }
        return hash;
    }

    function parseCsv(text) {
        const rows = [];
        let row = [], cell = '', inQuotes = false;
        for (let i = 0; i < text.length; i++) {
            const ch = text[i], next = text[i + 1];
            if (ch === '"' && inQuotes && next === '"') { cell += '"'; i++; }
            else if (ch === '"') { inQuotes = !inQuotes; }
            else if (ch === ',' && !inQuotes) { row.push(cell); cell = ''; }
            else if ((ch === '\n' || ch === '\r') && !inQuotes) {
                if (cell !== '' || row.length > 0) { row.push(cell); rows.push(row); row = []; cell = ''; }
            } else { cell += ch; }
        }
        if (cell !== '' || row.length > 0) { row.push(cell); rows.push(row); }
        return rows;
    }

    async function getCoverLetter(vacancyUrl) {
        const csvUrl = `https://docs.google.com/spreadsheets/d/${SPREADSHEET_ID}/gviz/tq?tqx=out:csv&gid=${SHEET_GID}`;
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method: 'GET',
                url: csvUrl,
                onload: (resp) => {
                    try {
                        const rows = parseCsv(resp.responseText);
                        if (!rows.length) { reject('Пустой CSV'); return; }
                        const headers = rows[0].map(h => h.trim().toLowerCase());
                        const urlIdx = headers.indexOf('url');
                        const letterIdx = headers.indexOf('cover-letter');
                        if (urlIdx === -1 || letterIdx === -1) { reject('Колонки url/cover-letter не найдены'); return; }
                        for (let i = 1; i < rows.length; i++) {
                            if (rows[i][urlIdx] && rows[i][urlIdx].includes(vacancyUrl)) {
                                resolve(rows[i][letterIdx]);
                                return;
                            }
                        }
                        reject('Вакансия не найдена в таблице');
                    } catch (e) { reject(e); }
                },
                onerror: reject
            });
        });
    }

    async function getPopupData(vacancyId) {
        const xsrf = getXsrf();
        const resp = await fetch(`/applicant/vacancy_response/popup?vacancyId=${vacancyId}`, {
            headers: { 'X-XSRFToken': xsrf },
            credentials: 'same-origin'
        });
        return resp.json();
    }

    async function sendResponse(vacancyId, resumeHash, letter) {
        const xsrf = getXsrf();
        const form = new FormData();
        form.append('_xsrf', xsrf);
        form.append('vacancy_id', vacancyId);
        form.append('resume_hash', resumeHash);
        form.append('ignore_postponed', 'true');
        form.append('incomplete', 'false');
        form.append('letter', letter);
        form.append('lux', 'true');
        form.append('withoutTest', 'no');
        return fetch('/applicant/vacancy_response/popup', { method: 'POST', body: form, credentials: 'same-origin' });
    }

    function addButton() {
        const btn = document.createElement('button');
        btn.innerText = '🚀 Автоотклик';
        btn.style.cssText = 'position:fixed;top:100px;right:20px;z-index:99999;padding:12px 16px;background:#0B1628;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px;';
        btn.onclick = async () => {
            const vacancyId = getVacancyId();
            if (!vacancyId) { alert('Не удалось определить ID вакансии'); return; }
            const resumeHash = getResumeHash();
            if (!resumeHash || resumeHash === 'YOUR_RESUME_HASH') {
                alert('Заполните DEFAULT_RESUME_HASH в скрипте');
                return;
            }

            btn.innerText = '⏳ Ищу письмо...';
            let letter;
            try {
                letter = await getCoverLetter(location.href.split('?')[0]);
            } catch (e) {
                letter = prompt('Письмо не найдено. Вставьте вручную:', '');
                if (!letter) return;
            }

            btn.innerText = '⏳ Отправляю...';
            try {
                const popup = await getPopupData(vacancyId);
                console.log('[HH Auto] popup:', popup);
                let finalResumeHash = resumeHash;
                if (!finalResumeHash && popup.resumes && popup.resumes.length) {
                    finalResumeHash = popup.resumes[0].hash;
                }
                const resp = await sendResponse(vacancyId, finalResumeHash, letter);
                const result = await resp.json().catch(() => ({}));
                console.log('[HH Auto] response:', resp.status, result);
                if (resp.ok) {
                    btn.innerText = '✅ Отклик отправлен';
                    btn.style.background = '#22c55e';
                } else {
                    btn.innerText = `❌ Ошибка ${resp.status}`;
                    btn.style.background = '#ef4444';
                    alert('Ошибка: ' + JSON.stringify(result));
                }
            } catch (e) {
                console.error(e);
                btn.innerText = '❌ Ошибка';
                btn.style.background = '#ef4444';
                alert('Ошибка: ' + e.message);
            }
        };
        document.body.appendChild(btn);
    }

    if (getVacancyId()) addButton();
})();
