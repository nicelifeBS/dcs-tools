#include "DcsProcessGuard.h"

#include <utility>

#ifdef Q_OS_WIN
// windows.h must come first: tlhelp32.h uses types (DWORD, WCHAR, HANDLE, ...) that
// only exist once windows.h has defined them.
#include <windows.h>
#include <tlhelp32.h>
#endif

DcsProcessGuard::DcsProcessGuard(ProcessListProvider processListProvider)
    : m_processListProvider(processListProvider ? std::move(processListProvider)
                                                  : ProcessListProvider(&DcsProcessGuard::platformProcessList))
{
}

bool DcsProcessGuard::isDcsRunning() const
{
    const QStringList processNames = m_processListProvider ? m_processListProvider() : QStringList();

    for (const QString &name : processNames) {
        if (name.compare(QString::fromLatin1(DcsExecutableName), Qt::CaseInsensitive) == 0)
            return true;
    }
    return false;
}

QStringList DcsProcessGuard::platformProcessList()
{
#ifdef Q_OS_WIN
    QStringList names;

    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE)
        return names;

    PROCESSENTRY32W entry;
    entry.dwSize = sizeof(PROCESSENTRY32W);
    if (Process32FirstW(snapshot, &entry)) {
        do {
            names << QString::fromWCharArray(entry.szExeFile);
        } while (Process32NextW(snapshot, &entry));
    }

    CloseHandle(snapshot);
    return names;
#else
    // No process enumeration available off Windows; treat as "nothing running" so the
    // guard never blocks a build/test on other platforms. Real usage is Windows-only,
    // and tests always inject an explicit provider instead of relying on this.
    return QStringList();
#endif
}
