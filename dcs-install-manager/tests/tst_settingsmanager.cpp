#include <QDir>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>

#include "core/settings/SettingsManager.h"

class tst_SettingsManager : public QObject
{
    Q_OBJECT

private slots:
    void freshFile_defaultsAreEmptyExceptVariant();
    void setters_persistAndAreReloadedByNewInstance();
    void setter_noOpAndNoSignalWhenValueUnchanged();
};

void tst_SettingsManager::freshFile_defaultsAreEmptyExceptVariant()
{
    QTemporaryDir tempDir;
    QVERIFY(tempDir.isValid());
    const QString settingsPath = QDir(tempDir.path()).filePath(QStringLiteral("settings.ini"));

    SettingsManager settings(settingsPath);
    QVERIFY(settings.dcsInstallPath().isEmpty());
    QCOMPARE(settings.dcsVariant(), QStringLiteral("stable"));
    QVERIFY(settings.savedGamesPath().isEmpty());
    QVERIFY(settings.libraryRootPath().isEmpty());
}

void tst_SettingsManager::setters_persistAndAreReloadedByNewInstance()
{
    QTemporaryDir tempDir;
    QVERIFY(tempDir.isValid());
    const QString settingsPath = QDir(tempDir.path()).filePath(QStringLiteral("settings.ini"));

    {
        SettingsManager settings(settingsPath);
        settings.setDcsInstallPath(QStringLiteral("C:/Games/DCS World"));
        settings.setDcsVariant(QStringLiteral("openbeta"));
        settings.setSavedGamesPath(QStringLiteral("C:/Users/me/Saved Games/DCS"));
        settings.setLibraryRootPath(QStringLiteral("C:/Users/me/DCS-ModLibrary"));
    }

    SettingsManager reloaded(settingsPath);
    QCOMPARE(reloaded.dcsInstallPath(), QStringLiteral("C:/Games/DCS World"));
    QCOMPARE(reloaded.dcsVariant(), QStringLiteral("openbeta"));
    QCOMPARE(reloaded.savedGamesPath(), QStringLiteral("C:/Users/me/Saved Games/DCS"));
    QCOMPARE(reloaded.libraryRootPath(), QStringLiteral("C:/Users/me/DCS-ModLibrary"));
}

void tst_SettingsManager::setter_noOpAndNoSignalWhenValueUnchanged()
{
    QTemporaryDir tempDir;
    QVERIFY(tempDir.isValid());
    const QString settingsPath = QDir(tempDir.path()).filePath(QStringLiteral("settings.ini"));

    SettingsManager settings(settingsPath);
    settings.setDcsInstallPath(QStringLiteral("C:/Games/DCS World"));

    QSignalSpy spy(&settings, &SettingsManager::dcsInstallPathChanged);
    settings.setDcsInstallPath(QStringLiteral("C:/Games/DCS World"));
    QCOMPARE(spy.count(), 0);
}

QTEST_APPLESS_MAIN(tst_SettingsManager)
#include "tst_settingsmanager.moc"
