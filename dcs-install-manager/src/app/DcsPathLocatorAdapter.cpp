#include "DcsPathLocatorAdapter.h"

#include "core/paths/DcsPathLocator.h"

#include <QVariantMap>

DcsPathLocatorAdapter::DcsPathLocatorAdapter(DcsPathLocator *locator, QObject *parent)
    : QObject(parent)
    , m_locator(locator)
{
}

QVariantList DcsPathLocatorAdapter::detectInstalls() const
{
    QVariantList results;
    if (!m_locator)
        return results;

    const QList<DcsPathLocator::DetectedInstall> installs = m_locator->detectInstalls();
    results.reserve(installs.size());
    for (const DcsPathLocator::DetectedInstall &install : installs) {
        results.append(QVariantMap{
            {QStringLiteral("variant"), install.variant},
            {QStringLiteral("path"), install.path},
        });
    }
    return results;
}

QString DcsPathLocatorAdapter::detectSavedGamesRoot() const
{
    return DcsPathLocator::detectSavedGamesRoot();
}

bool DcsPathLocatorAdapter::isValidInstallRoot(const QString &path) const
{
    return DcsPathLocator::isValidInstallRoot(path);
}
