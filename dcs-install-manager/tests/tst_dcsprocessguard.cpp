#include <QTest>

#include "core/safety/DcsProcessGuard.h"

class tst_DcsProcessGuard : public QObject
{
    Q_OBJECT

private slots:
    void isDcsRunning_trueWhenGameExeInList();
    void isDcsRunning_falseWhenOnlyUpdaterInList();
    void isDcsRunning_falseWhenListEmpty();
    void isDcsRunning_matchIsCaseInsensitive();
};

void tst_DcsProcessGuard::isDcsRunning_trueWhenGameExeInList()
{
    DcsProcessGuard guard([]() { return QStringList{QStringLiteral("DCS.exe")}; });
    QVERIFY(guard.isDcsRunning());
}

void tst_DcsProcessGuard::isDcsRunning_falseWhenOnlyUpdaterInList()
{
    // The launcher/updater process being open must never block anything.
    DcsProcessGuard guard([]() { return QStringList{QStringLiteral("DCS_updater.exe")}; });
    QVERIFY(!guard.isDcsRunning());
}

void tst_DcsProcessGuard::isDcsRunning_falseWhenListEmpty()
{
    DcsProcessGuard guard([]() { return QStringList{}; });
    QVERIFY(!guard.isDcsRunning());
}

void tst_DcsProcessGuard::isDcsRunning_matchIsCaseInsensitive()
{
    DcsProcessGuard guard([]() { return QStringList{QStringLiteral("dcs.exe")}; });
    QVERIFY(guard.isDcsRunning());
}

QTEST_APPLESS_MAIN(tst_DcsProcessGuard)
#include "tst_dcsprocessguard.moc"
