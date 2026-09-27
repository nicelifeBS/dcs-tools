#include <QCoreApplication>
#include <QDebug>
#include <QDir>
#include <QFile>
#include <QStandardPaths>

#include "core/catalog/ModCatalog.h"
#include "core/catalog/ModEntry.h"

// Milestone 1: backend-only console entry point. QML UI arrives in milestone 4 and
// will replace this with a QGuiApplication + QQmlApplicationEngine bootstrap.
int main(int argc, char *argv[])
{
    QCoreApplication app(argc, argv);
    QCoreApplication::setApplicationName(QStringLiteral("DCSInstallManager"));

    const QString appDataDir =
        QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
    const QString catalogPath = appDataDir + QStringLiteral("/catalog.json");

    if (!QFile::exists(catalogPath)) {
        QDir().mkpath(appDataDir);
        QFile::copy(QStringLiteral(":/data/default-catalog.json"), catalogPath);
    }

    ModCatalog catalog;
    if (!catalog.load(catalogPath)) {
        qWarning() << "Failed to load catalog at" << catalogPath;
        return 1;
    }

    qInfo() << "Catalog loaded from" << catalogPath << "-" << catalog.entries().size()
            << "entries";
    for (const ModEntry *entry : catalog.entries())
        qInfo() << " -" << entry->name() << "(" << entry->module() << "/" << entry->category() << ")";

    return 0;
}
