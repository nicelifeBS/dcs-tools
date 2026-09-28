#pragma once

#include <QObject>
#include <QString>
#include <QVariantMap>

class ModInstaller;

// Thin QObject wrapper around ModInstaller for QML: converts its plain-struct
// Result/ReinstallResult return values into QVariantMap so QML can read
// result.success / result.message / result.recoveredEntryIds directly.
//
// ModInstaller::installEntry/uninstallEntry/reinstallMissing already carry
// Q_INVOKABLE (milestone 4), but Qt 6.4's moc flattens Q_GADGET properties declared
// on structs nested inside a QObject class into the enclosing class's metaobject
// (a moc limitation, not something specific to this project), so those nested
// Result/ReinstallResult structs cannot themselves be made QML-property-readable
// without risking exactly that kind of moc corruption. This adapter is the
// straightforward, version-safe way around it, and it calls ModInstaller only through
// its normal (already public) C++ methods, unmodified.
class ModInstallerAdapter : public QObject
{
    Q_OBJECT

public:
    explicit ModInstallerAdapter(ModInstaller *installer, QObject *parent = nullptr);

    Q_INVOKABLE QVariantMap installEntry(const QString &entryId);
    Q_INVOKABLE QVariantMap uninstallEntry(const QString &entryId);
    Q_INVOKABLE QVariantMap reinstallMissing();

private:
    ModInstaller *m_installer;
};
