#include <QDebug>
#include <QDir>
#include <QFile>
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QStandardPaths>
#include <QUrl>

#include "app/ModInstallerAdapter.h"
#include "app/ModuleRuleResolverAdapter.h"
#include "core/catalog/ModCatalog.h"
#include "core/catalog/ModCatalogModel.h"
#include "core/install/InstallStateStore.h"
#include "core/install/ModInstaller.h"
#include "core/rules/ModuleRuleModel.h"
#include "core/rules/ModuleRuleStore.h"
#include "core/safety/DcsProcessGuard.h"

namespace {

// --- Milestone-5 stand-in -------------------------------------------------------
// ModInstaller needs a root-resolver callback to do anything at all. Real path
// resolution (DcsPathLocator auto-detecting Stable/Open Beta installs and Saved
// Games, plus SettingsManager-backed user overrides) is milestone 5. Until then,
// both installLocationKind values ("dcsInstall", "savedGames") resolve to two
// distinct subfolders under this app's own data directory, ignoring dcsVariant
// entirely, so Install/Uninstall are genuinely clickable and demoable today without
// needing a real DCS install on this machine. This is NOT the final behavior.
QString placeholderRootResolver(const QString &appDataDir, const QString &installLocationKind)
{
    const QString subfolder = installLocationKind == QStringLiteral("dcsInstall")
                                   ? QStringLiteral("_placeholder_dcsInstall")
                                   : QStringLiteral("_placeholder_savedGames");
    const QString root = QDir(appDataDir).filePath(subfolder);
    QDir().mkpath(root);
    return root;
}

} // namespace

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    QGuiApplication::setApplicationName(QStringLiteral("DCSInstallManager"));
    // Deliberately no setOrganizationName(): QStandardPaths::AppDataLocation nests
    // under organizationName/applicationName when both are set, which would resolve
    // to %APPDATA%\DCSInstallManager\DCSInstallManager\ instead of the plan's
    // %APPDATA%\DCSInstallManager\ - and would orphan any catalog/state data already
    // written there by earlier milestones' builds.

    const QString appDataDir =
        QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
    QDir().mkpath(appDataDir);

    const QString catalogPath = appDataDir + QStringLiteral("/catalog.json");
    const QString rulesPath = appDataDir + QStringLiteral("/module_rules.json");
    const QString installStatePath = appDataDir + QStringLiteral("/install_state.json");
    const QString backupsRootPath = appDataDir + QStringLiteral("/backups");

    if (!QFile::exists(catalogPath))
        QFile::copy(QStringLiteral(":/data/default-catalog.json"), catalogPath);
    if (!QFile::exists(rulesPath))
        QFile::copy(QStringLiteral(":/data/default-module-rules.json"), rulesPath);

    ModCatalog catalog;
    if (!catalog.load(catalogPath))
        qWarning() << "Failed to load catalog at" << catalogPath << "- starting empty.";

    ModuleRuleStore ruleStore;
    if (!ruleStore.load(rulesPath))
        qWarning() << "Failed to load module rules at" << rulesPath << "- starting empty.";

    InstallStateStore stateStore;
    if (!stateStore.load(installStatePath))
        qWarning() << "Failed to load install state at" << installStatePath << "- starting empty.";

    DcsProcessGuard processGuard;

    const ModInstaller::RootResolver rootResolver =
        [appDataDir](const QString &installLocationKind, const QString & /*dcsVariant*/) {
            return placeholderRootResolver(appDataDir, installLocationKind);
        };

    ModInstaller installer(&catalog, &stateStore, &processGuard, rootResolver, backupsRootPath);
    ModInstallerAdapter installerAdapter(&installer);

    ModCatalogModel catalogModel(&catalog);
    catalogModel.setInstallStateStore(&stateStore);

    ModuleRuleModel ruleModel(&ruleStore);
    ModuleRuleResolverAdapter ruleResolverAdapter(&ruleStore);

    // Persist to disk on every change. This is a local single-user desktop tool with
    // no explicit "Save" step anywhere in the UI, so saving on every CRUD/install
    // mutation is the simplest correct approach.
    QObject::connect(&catalog, &ModCatalog::catalogChanged, &catalog,
                      [&catalog, catalogPath]() { catalog.save(catalogPath); });
    QObject::connect(&ruleStore, &ModuleRuleStore::rulesChanged, &ruleStore,
                      [&ruleStore, rulesPath]() { ruleStore.save(rulesPath); });
    QObject::connect(&stateStore, &InstallStateStore::installStateChanged, &stateStore,
                      [&stateStore, installStatePath]() { stateStore.save(installStatePath); });

    QQmlApplicationEngine engine;

    // Without this, Qt 6.4's engine never finds this app's own compiled QML module
    // qmldir under its resource prefix ("locateLocalQmldir: DcsInstallManager
    // module's qmldir file not found"), because the default import path list never
    // includes ":/" itself - only "qrc:/qt-project.org/imports" (Qt's own modules)
    // is added automatically. Left unfixed, this silently breaks the Theme.qml
    // singleton (its properties read as undefined) and, worse, makes every QML file
    // in this module that is rooted at Popup/Dialog fail to resolve as a type at all
    // when declared as a child element (e.g. "AddEditEntryDialog is not a type") -
    // plain Item-rooted custom types still work without this because they are also
    // registered directly via the module's static C++ registration, which Popup-
    // rooted file components apparently are not, on this Qt version.
    engine.addImportPath(QStringLiteral(":/"));

    QQmlContext *rootContext = engine.rootContext();
    rootContext->setContextProperty(QStringLiteral("catalogModel"), &catalogModel);
    rootContext->setContextProperty(QStringLiteral("moduleRuleModel"), &ruleModel);
    rootContext->setContextProperty(QStringLiteral("ruleResolver"), &ruleResolverAdapter);
    rootContext->setContextProperty(QStringLiteral("modInstaller"), &installerAdapter);

    QObject::connect(
        &engine, &QQmlApplicationEngine::objectCreationFailed, &app,
        []() { QCoreApplication::exit(-1); }, Qt::QueuedConnection);

    engine.load(QUrl(QStringLiteral("qrc:/DcsInstallManager/src/qml/Main.qml")));

    if (engine.rootObjects().isEmpty())
        return -1;

    return app.exec();
}
