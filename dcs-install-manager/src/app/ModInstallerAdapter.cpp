#include "ModInstallerAdapter.h"

#include "core/install/ModInstaller.h"

ModInstallerAdapter::ModInstallerAdapter(ModInstaller *installer, QObject *parent)
    : QObject(parent)
    , m_installer(installer)
{
}

QVariantMap ModInstallerAdapter::installEntry(const QString &entryId)
{
    const ModInstaller::Result result = m_installer->installEntry(entryId);
    return {
        {QStringLiteral("success"), result.success},
        {QStringLiteral("message"), result.message},
    };
}

QVariantMap ModInstallerAdapter::uninstallEntry(const QString &entryId)
{
    const ModInstaller::Result result = m_installer->uninstallEntry(entryId);
    return {
        {QStringLiteral("success"), result.success},
        {QStringLiteral("message"), result.message},
    };
}

QVariantMap ModInstallerAdapter::reinstallMissing()
{
    const ModInstaller::ReinstallResult result = m_installer->reinstallMissing();
    return {
        {QStringLiteral("success"), result.success},
        {QStringLiteral("message"), result.message},
        {QStringLiteral("recoveredEntryIds"), result.recoveredEntryIds},
    };
}
