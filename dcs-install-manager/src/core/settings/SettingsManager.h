#pragma once

#include <QObject>
#include <QString>

#include <memory>

class QSettings;

// QSettings-backed store for the user's confirmed DCS paths. QSettings::IniFormat is
// pointed explicitly at <appDataDir>/settings.ini (never the registry) per the plan,
// so it's easy to inspect/back up by hand.
//
// Scoping note (milestone 5): the catalog data model lets a target request
// dcsVariant "stable"/"openbeta"/"any", implying a user could eventually have both
// DCS Stable and Open Beta installed with independently-configured paths. Full
// support for that is out of scope for this milestone: exactly one dcsInstallPath,
// one dcsVariant (which one the user says they picked - purely informational/for
// display) and one savedGamesPath are stored here. ModInstaller's root resolver
// (wired in main.cpp) ignores a target's requested dcsVariant entirely and always
// uses whatever single path is configured here, regardless of "stable"/"openbeta"/
// "any".
//
// Loads on construction; every setter writes straight through to QSettings (and
// syncs) and emits its change signal so QML bindings update live - same "no explicit
// Save button" pattern as ModCatalog/ModuleRuleStore/InstallStateStore in main.cpp,
// just backed directly by QSettings instead of a JSON round-trip.
class SettingsManager : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QString dcsInstallPath READ dcsInstallPath WRITE setDcsInstallPath NOTIFY dcsInstallPathChanged)
    Q_PROPERTY(QString dcsVariant READ dcsVariant WRITE setDcsVariant NOTIFY dcsVariantChanged)
    Q_PROPERTY(QString savedGamesPath READ savedGamesPath WRITE setSavedGamesPath NOTIFY savedGamesPathChanged)
    Q_PROPERTY(QString libraryRootPath READ libraryRootPath WRITE setLibraryRootPath NOTIFY libraryRootPathChanged)

public:
    // settingsFilePath is the absolute path to the .ini file (e.g.
    // <appDataDir>/settings.ini). The file/parent directory need not exist yet;
    // QSettings creates it on first write.
    explicit SettingsManager(const QString &settingsFilePath, QObject *parent = nullptr);
    ~SettingsManager() override;

    // Empty until the user confirms a path (first-run gate in Main.qml keys off this).
    QString dcsInstallPath() const;
    void setDcsInstallPath(const QString &path);

    // "stable" | "openbeta" - informational only in this milestone (see class
    // comment); defaults to "stable" when nothing has been saved yet.
    QString dcsVariant() const;
    void setDcsVariant(const QString &variant);

    QString savedGamesPath() const;
    void setSavedGamesPath(const QString &path);

    // Default folder AddEditEntryDialog's source-folder picker could start from;
    // optional, no first-run gating depends on it.
    QString libraryRootPath() const;
    void setLibraryRootPath(const QString &path);

signals:
    void dcsInstallPathChanged();
    void dcsVariantChanged();
    void savedGamesPathChanged();
    void libraryRootPathChanged();

private:
    std::unique_ptr<QSettings> m_settings;

    QString m_dcsInstallPath;
    QString m_dcsVariant;
    QString m_savedGamesPath;
    QString m_libraryRootPath;
};
