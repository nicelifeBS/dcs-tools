#include <QTemporaryDir>
#include <QTest>

#include "core/catalog/ModCatalog.h"
#include "core/catalog/ModEntry.h"

class tst_ModCatalog : public QObject
{
    Q_OBJECT

private slots:
    void addEntry_setsFieldsAndGeneratesUniqueId();
    void updateEntry_appliesOnlyGivenFields();
    void removeEntry_removesAndReturnsFalseIfMissing();
    void saveThenLoad_roundTripsAllFields();
    void load_missingFile_isNotAnError();
    void load_malformedFile_fails();
};

void tst_ModCatalog::addEntry_setsFieldsAndGeneratesUniqueId()
{
    ModCatalog catalog;

    const QVariantMap fieldsA{
        {"name", "Community A-10C II EFM Fix"},
        {"module", "A-10C II"},
        {"category", ModEntry::CategoryReinstallAfterUpdate},
    };
    const QVariantMap fieldsB{
        {"name", "Another Entry"},
        {"module", "F-16C"},
        {"category", ModEntry::CategoryLivery},
    };

    ModEntry *entryA = catalog.addEntry(fieldsA);
    ModEntry *entryB = catalog.addEntry(fieldsB);

    QVERIFY(entryA);
    QVERIFY(entryB);
    QVERIFY(!entryA->id().isEmpty());
    QVERIFY(entryA->id() != entryB->id());
    QCOMPARE(entryA->name(), QStringLiteral("Community A-10C II EFM Fix"));
    QCOMPARE(entryA->module(), QStringLiteral("A-10C II"));
    QCOMPARE(entryA->category(), QString(ModEntry::CategoryReinstallAfterUpdate));
    QVERIFY(!entryA->createdAt().isNull());
    QCOMPARE(entryA->createdAt(), entryA->updatedAt());
    QCOMPARE(catalog.entries().size(), 2);
}

void tst_ModCatalog::updateEntry_appliesOnlyGivenFields()
{
    ModCatalog catalog;
    ModEntry *entry = catalog.addEntry({
        {"name", "Original Name"},
        {"description", "Original description"},
        {"module", "A-10C II"},
    });
    const QDateTime originalUpdatedAt = entry->updatedAt();

    QTest::qSleep(5); // ensure updatedAt() actually advances
    const bool updated = catalog.updateEntry(entry->id(), {{"name", "New Name"}});

    QVERIFY(updated);
    QCOMPARE(entry->name(), QStringLiteral("New Name"));
    QCOMPARE(entry->description(), QStringLiteral("Original description")); // untouched
    QCOMPARE(entry->module(), QStringLiteral("A-10C II")); // untouched
    QVERIFY(entry->updatedAt() > originalUpdatedAt);

    QVERIFY(!catalog.updateEntry(QStringLiteral("not-a-real-id"), {{"name", "x"}}));
}

void tst_ModCatalog::removeEntry_removesAndReturnsFalseIfMissing()
{
    ModCatalog catalog;
    ModEntry *entry = catalog.addEntry({{"name", "To Delete"}});
    const QString id = entry->id();

    QCOMPARE(catalog.entries().size(), 1);
    QVERIFY(catalog.removeEntry(id));
    QCOMPARE(catalog.entries().size(), 0);
    QVERIFY(!catalog.findById(id));

    QVERIFY(!catalog.removeEntry(id)); // already gone
}

void tst_ModCatalog::saveThenLoad_roundTripsAllFields()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString filePath = dir.filePath(QStringLiteral("catalog.json"));

    ModCatalog original;
    original.addEntry({
        {"name", "Community A-10C II EFM Fix"},
        {"description", "Corrected flight model data files."},
        {"module", "A-10C II"},
        {"category", ModEntry::CategoryReinstallAfterUpdate},
        {"tags", QStringList{"A-10C", "EFM"}},
        {"source", QVariantMap{{"kind", "folder"}, {"path", "C:/lib/A10CEFM"}}},
        {"targets",
         QVariantList{QVariantMap{
             {"installLocationKind", "dcsInstall"},
             {"dcsVariant", "openbeta"},
             {"relativePath", "Mods/aircraft/A-10C II/Cockpit/Scripts"},
             {"fileMappings", QVariantList{}},
         }}},
        {"needsReinstallAfterUpdate", true},
        {"notes", "some notes"},
    });

    QVERIFY(original.save(filePath));

    ModCatalog loaded;
    QVERIFY(loaded.load(filePath));
    QCOMPARE(loaded.entries().size(), 1);

    ModEntry *originalEntry = original.entries().first();
    ModEntry *loadedEntry = loaded.entries().first();

    QCOMPARE(loadedEntry->id(), originalEntry->id());
    QCOMPARE(loadedEntry->name(), originalEntry->name());
    QCOMPARE(loadedEntry->description(), originalEntry->description());
    QCOMPARE(loadedEntry->module(), originalEntry->module());
    QCOMPARE(loadedEntry->category(), originalEntry->category());
    QCOMPARE(loadedEntry->tags(), originalEntry->tags());
    QCOMPARE(loadedEntry->source(), originalEntry->source());
    QCOMPARE(loadedEntry->targets(), originalEntry->targets());
    QCOMPARE(loadedEntry->needsReinstallAfterUpdate(), originalEntry->needsReinstallAfterUpdate());
    QCOMPARE(loadedEntry->notes(), originalEntry->notes());
}

void tst_ModCatalog::load_missingFile_isNotAnError()
{
    ModCatalog catalog;
    QVERIFY(catalog.load(QStringLiteral("/nonexistent/path/catalog.json")));
    QCOMPARE(catalog.entries().size(), 0);
}

void tst_ModCatalog::load_malformedFile_fails()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString filePath = dir.filePath(QStringLiteral("bad.json"));

    QFile file(filePath);
    QVERIFY(file.open(QIODevice::WriteOnly));
    file.write("{ not valid json");
    file.close();

    ModCatalog catalog;
    QVERIFY(!catalog.load(filePath));
}

QTEST_APPLESS_MAIN(tst_ModCatalog)
#include "tst_modcatalog.moc"
