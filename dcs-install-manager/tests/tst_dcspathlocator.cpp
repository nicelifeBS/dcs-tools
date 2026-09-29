#include <QDir>
#include <QFile>
#include <QTemporaryDir>
#include <QTest>

#include "core/paths/DcsPathLocator.h"

class tst_DcsPathLocator : public QObject
{
    Q_OBJECT

private slots:
    void isValidInstallRoot_trueWhenBinDcsExePresent();
    void isValidInstallRoot_trueWhenBinMtDcsExePresent();
    void isValidInstallRoot_falseWhenNeitherPresent();
    void isValidInstallRoot_falseForEmptyPath();

    void variantForPath_tagsOpenBetaCaseInsensitively();
    void variantForPath_tagsStableWhenNoOpenBetaHint();

    void detectInstalls_filtersToValidCandidatesAndTagsVariant();
    void detectInstalls_emptyWhenProviderReturnsNothing();
    void detectInstalls_emptyWhenNoCandidateIsValid();

    void parseSteamLibraryFolders_extractsAllPathsFromSampleVdf();
    void parseSteamLibraryFolders_emptyForContentWithNoPaths();
    void parseSteamLibraryFolders_unescapesDoubledBackslashes();

    void savedGamesPathForVariant_appendsDcsForStable();
    void savedGamesPathForVariant_appendsDcsOpenBetaForOpenBeta();
    void savedGamesPathForVariant_isCaseInsensitiveOnVariant();
    void savedGamesPathForVariant_emptyWhenBaseIsEmpty();
};

namespace {

// Creates <root>/<subdir>/dcs.exe (and its parent dirs) so isValidInstallRoot()/
// detectInstalls() have something real to find on disk.
void makeFakeInstall(const QString &root, const QString &subdir)
{
    const QString dir = QDir(root).filePath(subdir);
    QVERIFY(QDir().mkpath(dir));
    QFile exe(QDir(dir).filePath(QStringLiteral("dcs.exe")));
    QVERIFY(exe.open(QIODevice::WriteOnly));
    exe.close();
}

} // namespace

void tst_DcsPathLocator::isValidInstallRoot_trueWhenBinDcsExePresent()
{
    QTemporaryDir tempDir;
    QVERIFY(tempDir.isValid());
    makeFakeInstall(tempDir.path(), QStringLiteral("bin"));

    QVERIFY(DcsPathLocator::isValidInstallRoot(tempDir.path()));
}

void tst_DcsPathLocator::isValidInstallRoot_trueWhenBinMtDcsExePresent()
{
    QTemporaryDir tempDir;
    QVERIFY(tempDir.isValid());
    makeFakeInstall(tempDir.path(), QStringLiteral("bin-mt"));

    QVERIFY(DcsPathLocator::isValidInstallRoot(tempDir.path()));
}

void tst_DcsPathLocator::isValidInstallRoot_falseWhenNeitherPresent()
{
    QTemporaryDir tempDir;
    QVERIFY(tempDir.isValid());
    QVERIFY(QDir().mkpath(QDir(tempDir.path()).filePath(QStringLiteral("bin"))));
    // "bin" exists but has no dcs.exe in it.

    QVERIFY(!DcsPathLocator::isValidInstallRoot(tempDir.path()));
}

void tst_DcsPathLocator::isValidInstallRoot_falseForEmptyPath()
{
    QVERIFY(!DcsPathLocator::isValidInstallRoot(QString()));
}

void tst_DcsPathLocator::variantForPath_tagsOpenBetaCaseInsensitively()
{
    QCOMPARE(DcsPathLocator::variantForPath(QStringLiteral("C:/Games/DCS World OpenBeta")),
             QStringLiteral("openbeta"));
    QCOMPARE(DcsPathLocator::variantForPath(QStringLiteral("C:/Games/DCS World OPENBETA")),
             QStringLiteral("openbeta"));
}

void tst_DcsPathLocator::variantForPath_tagsStableWhenNoOpenBetaHint()
{
    QCOMPARE(DcsPathLocator::variantForPath(QStringLiteral("C:/Games/DCS World")),
             QStringLiteral("stable"));
}

void tst_DcsPathLocator::detectInstalls_filtersToValidCandidatesAndTagsVariant()
{
    QTemporaryDir tempDir;
    QVERIFY(tempDir.isValid());

    const QString stablePath = QDir(tempDir.path()).filePath(QStringLiteral("DCS World"));
    const QString openBetaPath = QDir(tempDir.path()).filePath(QStringLiteral("DCS World OpenBeta"));
    const QString invalidPath = QDir(tempDir.path()).filePath(QStringLiteral("NotAnInstall"));

    makeFakeInstall(stablePath, QStringLiteral("bin"));
    makeFakeInstall(openBetaPath, QStringLiteral("bin-mt"));
    QVERIFY(QDir().mkpath(invalidPath)); // exists, but no bin/bin-mt with dcs.exe

    DcsPathLocator locator([stablePath, openBetaPath, invalidPath]() {
        return QStringList{stablePath, openBetaPath, invalidPath};
    });

    const QList<DcsPathLocator::DetectedInstall> results = locator.detectInstalls();
    QCOMPARE(results.size(), 2);

    QVERIFY(results[0].path == stablePath || results[1].path == stablePath);
    QVERIFY(results[0].path == openBetaPath || results[1].path == openBetaPath);

    for (const auto &result : results) {
        if (result.path == stablePath)
            QCOMPARE(result.variant, QStringLiteral("stable"));
        else if (result.path == openBetaPath)
            QCOMPARE(result.variant, QStringLiteral("openbeta"));
    }
}

void tst_DcsPathLocator::detectInstalls_emptyWhenProviderReturnsNothing()
{
    DcsPathLocator locator([]() { return QStringList{}; });
    QVERIFY(locator.detectInstalls().isEmpty());
}

void tst_DcsPathLocator::detectInstalls_emptyWhenNoCandidateIsValid()
{
    QTemporaryDir tempDir;
    QVERIFY(tempDir.isValid());
    const QString notAnInstall = QDir(tempDir.path()).filePath(QStringLiteral("Empty"));
    QVERIFY(QDir().mkpath(notAnInstall));

    DcsPathLocator locator([notAnInstall]() { return QStringList{notAnInstall}; });
    QVERIFY(locator.detectInstalls().isEmpty());
}

void tst_DcsPathLocator::parseSteamLibraryFolders_extractsAllPathsFromSampleVdf()
{
    // Realistic libraryfolders.vdf content (Valve's KeyValues text format), reflecting
    // nested braces, tab-separated key/value pairs, and numbered top-level keys.
    const QString vdf = QStringLiteral(
        "\"libraryfolders\"\n"
        "{\n"
        "\t\"0\"\n"
        "\t{\n"
        "\t\t\"path\"\t\t\"C:\\\\Program Files (x86)\\\\Steam\"\n"
        "\t\t\"label\"\t\t\"\"\n"
        "\t\t\"contentid\"\t\t\"1234567890123456789\"\n"
        "\t\t\"totalsize\"\t\t\"0\"\n"
        "\t\t\"update_clean_bytes_tally\"\t\t\"0\"\n"
        "\t\t\"time_last_update_corruption\"\t\t\"0\"\n"
        "\t\t\"apps\"\n"
        "\t\t{\n"
        "\t\t\t\"223750\"\t\t\"12345678901\"\n"
        "\t\t}\n"
        "\t}\n"
        "\t\"1\"\n"
        "\t{\n"
        "\t\t\"path\"\t\t\"D:\\\\SteamLibrary\"\n"
        "\t\t\"label\"\t\t\"\"\n"
        "\t\t\"contentid\"\t\t\"9876543210987654321\"\n"
        "\t\t\"totalsize\"\t\t\"0\"\n"
        "\t\t\"update_clean_bytes_tally\"\t\t\"0\"\n"
        "\t\t\"time_last_update_corruption\"\t\t\"0\"\n"
        "\t\t\"apps\"\n"
        "\t\t{\n"
        "\t\t\t\"223750\"\t\t\"98765432109\"\n"
        "\t\t}\n"
        "\t}\n"
        "}\n");

    const QStringList paths = DcsPathLocator::parseSteamLibraryFolders(vdf);

    QCOMPARE(paths.size(), 2);
    QCOMPARE(paths.at(0), QStringLiteral("C:\\Program Files (x86)\\Steam"));
    QCOMPARE(paths.at(1), QStringLiteral("D:\\SteamLibrary"));
}

void tst_DcsPathLocator::parseSteamLibraryFolders_emptyForContentWithNoPaths()
{
    QVERIFY(DcsPathLocator::parseSteamLibraryFolders(QString()).isEmpty());
    QVERIFY(DcsPathLocator::parseSteamLibraryFolders(QStringLiteral("\"libraryfolders\"\n{\n}\n")).isEmpty());
}

void tst_DcsPathLocator::parseSteamLibraryFolders_unescapesDoubledBackslashes()
{
    const QString vdf = QStringLiteral("\"path\"\t\t\"E:\\\\Games\\\\SteamLibrary\"\n");
    const QStringList paths = DcsPathLocator::parseSteamLibraryFolders(vdf);

    QCOMPARE(paths.size(), 1);
    QCOMPARE(paths.at(0), QStringLiteral("E:\\Games\\SteamLibrary"));
}

void tst_DcsPathLocator::savedGamesPathForVariant_appendsDcsForStable()
{
    QCOMPARE(DcsPathLocator::savedGamesPathForVariant(QStringLiteral("C:/Users/bjoern/Saved Games"),
                                                       QStringLiteral("stable")),
             QStringLiteral("C:/Users/bjoern/Saved Games/DCS"));
}

void tst_DcsPathLocator::savedGamesPathForVariant_appendsDcsOpenBetaForOpenBeta()
{
    QCOMPARE(DcsPathLocator::savedGamesPathForVariant(QStringLiteral("C:/Users/bjoern/Saved Games"),
                                                       QStringLiteral("openbeta")),
             QStringLiteral("C:/Users/bjoern/Saved Games/DCS.openbeta"));
}

void tst_DcsPathLocator::savedGamesPathForVariant_isCaseInsensitiveOnVariant()
{
    QCOMPARE(DcsPathLocator::savedGamesPathForVariant(QStringLiteral("C:/Saved Games"),
                                                       QStringLiteral("OpenBeta")),
             QStringLiteral("C:/Saved Games/DCS.openbeta"));
}

void tst_DcsPathLocator::savedGamesPathForVariant_emptyWhenBaseIsEmpty()
{
    QVERIFY(DcsPathLocator::savedGamesPathForVariant(QString(), QStringLiteral("stable")).isEmpty());
}

QTEST_APPLESS_MAIN(tst_DcsPathLocator)
#include "tst_dcspathlocator.moc"
