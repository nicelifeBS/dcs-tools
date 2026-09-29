#include "SettingsManager.h"

#include <QSettings>

namespace {
const QString kDcsInstallPathKey = QStringLiteral("dcsInstallPath");
const QString kDcsVariantKey = QStringLiteral("dcsVariant");
const QString kSavedGamesPathKey = QStringLiteral("savedGamesPath");
const QString kLibraryRootPathKey = QStringLiteral("libraryRootPath");
const QString kDefaultVariant = QStringLiteral("stable");
} // namespace

SettingsManager::SettingsManager(const QString &settingsFilePath, QObject *parent)
    : QObject(parent)
    , m_settings(std::make_unique<QSettings>(settingsFilePath, QSettings::IniFormat))
{
    m_dcsInstallPath = m_settings->value(kDcsInstallPathKey).toString();
    m_dcsVariant = m_settings->value(kDcsVariantKey, kDefaultVariant).toString();
    m_savedGamesPath = m_settings->value(kSavedGamesPathKey).toString();
    m_libraryRootPath = m_settings->value(kLibraryRootPathKey).toString();
}

SettingsManager::~SettingsManager() = default;

QString SettingsManager::dcsInstallPath() const
{
    return m_dcsInstallPath;
}

void SettingsManager::setDcsInstallPath(const QString &path)
{
    if (m_dcsInstallPath == path)
        return;
    m_dcsInstallPath = path;
    m_settings->setValue(kDcsInstallPathKey, m_dcsInstallPath);
    m_settings->sync();
    emit dcsInstallPathChanged();
}

QString SettingsManager::dcsVariant() const
{
    return m_dcsVariant;
}

void SettingsManager::setDcsVariant(const QString &variant)
{
    if (m_dcsVariant == variant)
        return;
    m_dcsVariant = variant;
    m_settings->setValue(kDcsVariantKey, m_dcsVariant);
    m_settings->sync();
    emit dcsVariantChanged();
}

QString SettingsManager::savedGamesPath() const
{
    return m_savedGamesPath;
}

void SettingsManager::setSavedGamesPath(const QString &path)
{
    if (m_savedGamesPath == path)
        return;
    m_savedGamesPath = path;
    m_settings->setValue(kSavedGamesPathKey, m_savedGamesPath);
    m_settings->sync();
    emit savedGamesPathChanged();
}

QString SettingsManager::libraryRootPath() const
{
    return m_libraryRootPath;
}

void SettingsManager::setLibraryRootPath(const QString &path)
{
    if (m_libraryRootPath == path)
        return;
    m_libraryRootPath = path;
    m_settings->setValue(kLibraryRootPathKey, m_libraryRootPath);
    m_settings->sync();
    emit libraryRootPathChanged();
}
