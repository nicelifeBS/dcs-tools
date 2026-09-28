#include <QTemporaryDir>
#include <QTest>

#include "core/rules/ModuleRule.h"
#include "core/rules/ModuleRuleResolver.h"
#include "core/rules/ModuleRuleStore.h"

class tst_ModuleRuleResolver : public QObject
{
    Q_OBJECT

private slots:
    void resolve_moduleSpecificRuleWinsOverCategoryDefault();
    void resolve_fallsBackToCategoryDefaultWhenNoModuleRuleMatches();
    void resolve_returnsEmptyWhenNeitherRuleNorDefaultExists();
    void resolve_substitutesModuleAndEntryNamePlaceholders();
    void resolve_moduleMatchIsCaseInsensitive();
    void moduleRuleStore_saveThenLoad_roundTripsRulesAndDefaults();
};

namespace {

// Builds a store with the shipped built-in livery default and no override rules.
ModuleRuleStore *makeStoreWithLiveryDefault(QObject *parent)
{
    auto *store = new ModuleRuleStore(parent);
    store->setDefaultForCategory(QStringLiteral("livery"),
                                  QVariantMap{
                                      {"installLocationKind", "savedGames"},
                                      {"dcsVariant", "any"},
                                      {"pathTemplate", "Liveries/{module}/{entryName}"},
                                  });
    return store;
}

} // namespace

void tst_ModuleRuleResolver::resolve_moduleSpecificRuleWinsOverCategoryDefault()
{
    ModuleRuleStore store;
    store.setDefaultForCategory(QStringLiteral("livery"),
                                 QVariantMap{
                                     {"installLocationKind", "savedGames"},
                                     {"dcsVariant", "any"},
                                     {"pathTemplate", "Liveries/{module}/{entryName}"},
                                 });
    store.addRule({
        {"module", "A-10C II"},
        {"category", "livery"},
        {"installLocationKind", "dcsInstall"},
        {"dcsVariant", "any"},
        {"pathTemplate", "Bazar/Liveries/{module}/{entryName}"},
    });

    ModuleRuleResolver resolver(&store);
    const QVariantMap target = resolver.resolve(QStringLiteral("A-10C II"),
                                                  QStringLiteral("livery"),
                                                  QStringLiteral("My Livery"));

    QVERIFY(!target.isEmpty());
    QCOMPARE(target.value("installLocationKind").toString(), QStringLiteral("dcsInstall"));
    QCOMPARE(target.value("dcsVariant").toString(), QStringLiteral("any"));
    QCOMPARE(target.value("relativePath").toString(),
             QStringLiteral("Bazar/Liveries/A-10C II/My Livery"));
    QVERIFY(target.value("fileMappings").toList().isEmpty());
}

void tst_ModuleRuleResolver::resolve_fallsBackToCategoryDefaultWhenNoModuleRuleMatches()
{
    ModuleRuleStore *store = makeStoreWithLiveryDefault(this);
    // An override rule for a different module must not interfere.
    store->addRule({
        {"module", "A-10C II"},
        {"category", "livery"},
        {"installLocationKind", "dcsInstall"},
        {"dcsVariant", "any"},
        {"pathTemplate", "Bazar/Liveries/{module}/{entryName}"},
    });

    ModuleRuleResolver resolver(store);
    const QVariantMap target = resolver.resolve(QStringLiteral("F-16C"),
                                                  QStringLiteral("livery"),
                                                  QStringLiteral("Viper Skin"));

    QVERIFY(!target.isEmpty());
    QCOMPARE(target.value("installLocationKind").toString(), QStringLiteral("savedGames"));
    QCOMPARE(target.value("dcsVariant").toString(), QStringLiteral("any"));
    QCOMPARE(target.value("relativePath").toString(),
             QStringLiteral("Liveries/F-16C/Viper Skin"));
}

void tst_ModuleRuleResolver::resolve_returnsEmptyWhenNeitherRuleNorDefaultExists()
{
    ModuleRuleStore *store = makeStoreWithLiveryDefault(this);

    ModuleRuleResolver resolver(store);
    // "misc" has no built-in default and no override rule was added for it.
    const QVariantMap target = resolver.resolve(QStringLiteral("F-16C"),
                                                  QStringLiteral("misc"),
                                                  QStringLiteral("Some Misc Thing"));

    QVERIFY(target.isEmpty());
}

void tst_ModuleRuleResolver::resolve_substitutesModuleAndEntryNamePlaceholders()
{
    ModuleRuleStore store;
    store.addRule({
        {"module", "Ka-50"},
        {"category", "aircraft-library"},
        {"installLocationKind", "dcsInstall"},
        {"dcsVariant", "stable"},
        {"pathTemplate", "Mods/aircraft/{module}/Extras/{entryName}"},
    });

    ModuleRuleResolver resolver(&store);
    const QVariantMap target = resolver.resolve(QStringLiteral("Ka-50"),
                                                  QStringLiteral("aircraft-library"),
                                                  QStringLiteral("Cockpit Fix"));

    QCOMPARE(target.value("relativePath").toString(),
             QStringLiteral("Mods/aircraft/Ka-50/Extras/Cockpit Fix"));
}

void tst_ModuleRuleResolver::resolve_moduleMatchIsCaseInsensitive()
{
    ModuleRuleStore store;
    store.addRule({
        {"module", "A-10C II"},
        {"category", "livery"},
        {"installLocationKind", "dcsInstall"},
        {"dcsVariant", "any"},
        {"pathTemplate", "Bazar/Liveries/{module}/{entryName}"},
    });

    ModuleRuleResolver resolver(&store);
    const QVariantMap target = resolver.resolve(QStringLiteral("a-10c ii"),
                                                  QStringLiteral("livery"),
                                                  QStringLiteral("My Livery"));

    QVERIFY(!target.isEmpty());
    QCOMPARE(target.value("installLocationKind").toString(), QStringLiteral("dcsInstall"));
    QCOMPARE(target.value("relativePath").toString(),
             QStringLiteral("Bazar/Liveries/a-10c ii/My Livery"));
}

void tst_ModuleRuleResolver::moduleRuleStore_saveThenLoad_roundTripsRulesAndDefaults()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString filePath = dir.filePath(QStringLiteral("module_rules.json"));

    ModuleRuleStore original;
    original.setDefaultForCategory(QStringLiteral("livery"),
                                    QVariantMap{
                                        {"installLocationKind", "savedGames"},
                                        {"dcsVariant", "any"},
                                        {"pathTemplate", "Liveries/{module}/{entryName}"},
                                    });
    original.addRule({
        {"module", "A-10C II"},
        {"category", "livery"},
        {"installLocationKind", "dcsInstall"},
        {"dcsVariant", "any"},
        {"pathTemplate", "Bazar/Liveries/{module}/{entryName}"},
        {"notes", "This module reads liveries from the install dir, not Saved Games."},
    });

    QVERIFY(original.save(filePath));

    ModuleRuleStore loaded;
    QVERIFY(loaded.load(filePath));

    QCOMPARE(loaded.defaultForCategory(QStringLiteral("livery")),
             original.defaultForCategory(QStringLiteral("livery")));

    QCOMPARE(loaded.moduleRules().size(), 1);
    ModuleRule *originalRule = original.moduleRules().first();
    ModuleRule *loadedRule = loaded.moduleRules().first();

    QCOMPARE(loadedRule->id(), originalRule->id());
    QCOMPARE(loadedRule->module(), originalRule->module());
    QCOMPARE(loadedRule->category(), originalRule->category());
    QCOMPARE(loadedRule->installLocationKind(), originalRule->installLocationKind());
    QCOMPARE(loadedRule->dcsVariant(), originalRule->dcsVariant());
    QCOMPARE(loadedRule->pathTemplate(), originalRule->pathTemplate());
    QCOMPARE(loadedRule->notes(), originalRule->notes());
}

QTEST_APPLESS_MAIN(tst_ModuleRuleResolver)
#include "tst_moduleruleresolver.moc"
