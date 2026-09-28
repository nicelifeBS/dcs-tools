#include "ModuleRule.h"

#include <QJsonObject>

ModuleRule::ModuleRule(const QString &id, QObject *parent)
    : QObject(parent)
    , m_id(id)
{
}

QString ModuleRule::id() const
{
    return m_id;
}

QString ModuleRule::module() const
{
    return m_module;
}

void ModuleRule::setModule(const QString &module)
{
    if (m_module == module)
        return;
    m_module = module;
    emit moduleChanged();
}

QString ModuleRule::category() const
{
    return m_category;
}

void ModuleRule::setCategory(const QString &category)
{
    if (m_category == category)
        return;
    m_category = category;
    emit categoryChanged();
}

QString ModuleRule::installLocationKind() const
{
    return m_installLocationKind;
}

void ModuleRule::setInstallLocationKind(const QString &installLocationKind)
{
    if (m_installLocationKind == installLocationKind)
        return;
    m_installLocationKind = installLocationKind;
    emit installLocationKindChanged();
}

QString ModuleRule::dcsVariant() const
{
    return m_dcsVariant;
}

void ModuleRule::setDcsVariant(const QString &dcsVariant)
{
    if (m_dcsVariant == dcsVariant)
        return;
    m_dcsVariant = dcsVariant;
    emit dcsVariantChanged();
}

QString ModuleRule::pathTemplate() const
{
    return m_pathTemplate;
}

void ModuleRule::setPathTemplate(const QString &pathTemplate)
{
    if (m_pathTemplate == pathTemplate)
        return;
    m_pathTemplate = pathTemplate;
    emit pathTemplateChanged();
}

QString ModuleRule::notes() const
{
    return m_notes;
}

void ModuleRule::setNotes(const QString &notes)
{
    if (m_notes == notes)
        return;
    m_notes = notes;
    emit notesChanged();
}

void ModuleRule::applyFields(const QVariantMap &fields)
{
    if (fields.contains(QStringLiteral("module")))
        setModule(fields.value(QStringLiteral("module")).toString());
    if (fields.contains(QStringLiteral("category")))
        setCategory(fields.value(QStringLiteral("category")).toString());
    if (fields.contains(QStringLiteral("installLocationKind"))) {
        setInstallLocationKind(
            fields.value(QStringLiteral("installLocationKind")).toString());
    }
    if (fields.contains(QStringLiteral("dcsVariant")))
        setDcsVariant(fields.value(QStringLiteral("dcsVariant")).toString());
    if (fields.contains(QStringLiteral("pathTemplate")))
        setPathTemplate(fields.value(QStringLiteral("pathTemplate")).toString());
    if (fields.contains(QStringLiteral("notes")))
        setNotes(fields.value(QStringLiteral("notes")).toString());
}

QJsonObject ModuleRule::toJson() const
{
    QJsonObject json;
    json[QStringLiteral("id")] = m_id;
    json[QStringLiteral("module")] = m_module;
    json[QStringLiteral("category")] = m_category;
    json[QStringLiteral("installLocationKind")] = m_installLocationKind;
    json[QStringLiteral("dcsVariant")] = m_dcsVariant;
    json[QStringLiteral("pathTemplate")] = m_pathTemplate;
    json[QStringLiteral("notes")] = m_notes;
    return json;
}

ModuleRule *ModuleRule::fromJson(const QJsonObject &json, QObject *parent)
{
    auto *rule = new ModuleRule(json.value(QStringLiteral("id")).toString(), parent);
    rule->setModule(json.value(QStringLiteral("module")).toString());
    rule->setCategory(json.value(QStringLiteral("category")).toString());
    rule->setInstallLocationKind(json.value(QStringLiteral("installLocationKind"))
                                      .toString(QString::fromLatin1(LocationSavedGames)));
    rule->setDcsVariant(
        json.value(QStringLiteral("dcsVariant")).toString(QString::fromLatin1(VariantAny)));
    rule->setPathTemplate(json.value(QStringLiteral("pathTemplate")).toString());
    rule->setNotes(json.value(QStringLiteral("notes")).toString());
    return rule;
}
