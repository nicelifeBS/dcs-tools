#pragma once

#include <QObject>
#include <QString>
#include <QVariantMap>

class QJsonObject;

// One module-rule override row: for a given (module, category), where content should
// install by default instead of falling back to the category's built-in default. See
// dcs-install-manager/data/default-module-rules.json for the JSON shape.
class ModuleRule : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QString id READ id CONSTANT)
    Q_PROPERTY(QString module READ module WRITE setModule NOTIFY moduleChanged)
    Q_PROPERTY(QString category READ category WRITE setCategory NOTIFY categoryChanged)
    Q_PROPERTY(QString installLocationKind READ installLocationKind WRITE
                   setInstallLocationKind NOTIFY installLocationKindChanged)
    Q_PROPERTY(QString dcsVariant READ dcsVariant WRITE setDcsVariant NOTIFY dcsVariantChanged)
    Q_PROPERTY(QString pathTemplate READ pathTemplate WRITE setPathTemplate NOTIFY
                   pathTemplateChanged)
    Q_PROPERTY(QString notes READ notes WRITE setNotes NOTIFY notesChanged)

public:
    // installLocationKind values.
    static constexpr const char *LocationDcsInstall = "dcsInstall";
    static constexpr const char *LocationSavedGames = "savedGames";

    // dcsVariant values.
    static constexpr const char *VariantStable = "stable";
    static constexpr const char *VariantOpenBeta = "openbeta";
    static constexpr const char *VariantAny = "any";

    explicit ModuleRule(const QString &id, QObject *parent = nullptr);

    QString id() const;

    QString module() const;
    void setModule(const QString &module);

    QString category() const;
    void setCategory(const QString &category);

    QString installLocationKind() const;
    void setInstallLocationKind(const QString &installLocationKind);

    QString dcsVariant() const;
    void setDcsVariant(const QString &dcsVariant);

    QString pathTemplate() const;
    void setPathTemplate(const QString &pathTemplate);

    QString notes() const;
    void setNotes(const QString &notes);

    // Applies whichever of the given fields are present (by key), leaving the rest
    // untouched. Used by ModuleRuleStore::addRule/updateRule so callers can pass
    // partial field maps.
    void applyFields(const QVariantMap &fields);

    QJsonObject toJson() const;
    static ModuleRule *fromJson(const QJsonObject &json, QObject *parent = nullptr);

signals:
    void moduleChanged();
    void categoryChanged();
    void installLocationKindChanged();
    void dcsVariantChanged();
    void pathTemplateChanged();
    void notesChanged();

private:
    QString m_id;
    QString m_module;
    QString m_category;
    QString m_installLocationKind = LocationSavedGames;
    QString m_dcsVariant = VariantAny;
    QString m_pathTemplate;
    QString m_notes;
};
