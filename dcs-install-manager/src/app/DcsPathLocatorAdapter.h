#pragma once

#include <QObject>
#include <QString>
#include <QVariantList>

class DcsPathLocator;

// Thin QObject wrapper exposing DcsPathLocator to QML - same
// thin-adapter-around-a-plain-class pattern as ModuleRuleResolverAdapter/
// ModInstallerAdapter. DcsPathLocator itself stays a plain, non-QObject class (it is
// unit-tested directly as such in tst_dcspathlocator.cpp); this adapter is the only
// QML-facing surface for it, used by PathSetupForm.qml's "Detect Installs"/"Detect
// Saved Games" buttons and validity indicator.
class DcsPathLocatorAdapter : public QObject
{
    Q_OBJECT

public:
    explicit DcsPathLocatorAdapter(DcsPathLocator *locator, QObject *parent = nullptr);

    // Each entry is a {variant, path} map, mirroring DcsPathLocator::DetectedInstall.
    Q_INVOKABLE QVariantList detectInstalls() const;

    Q_INVOKABLE QString detectSavedGamesRoot(const QString &variant) const;

    Q_INVOKABLE bool isValidInstallRoot(const QString &path) const;

private:
    DcsPathLocator *m_locator;
};
