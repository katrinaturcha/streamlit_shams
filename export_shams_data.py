import csv
from pathlib import Path

from django.db import connection

from main.management.commands import CustomBaseCommand
from providers.models import (
    Provider,
    ProviderActivityType,
    ProviderActivityTypeClass,
    ProviderActivityTypeGroup,
)


class Command(CustomBaseCommand):
    help = "Export SHAMS provider data (ID: 1)"

    PROVIDER_ID = 1
    BASE_PATH = Path(__file__).parent.parent.parent.parent
    CLASSES_CSV = BASE_PATH / "SHAMS.Class.export.csv"
    GROUPS_CSV = BASE_PATH / "SHAMS.Groups.export.csv"
    ACTIVITIES_CSV = BASE_PATH / "SHAMS.export.csv"

    def add_arguments(self, parser):
        parser.add_argument(
            "--provider-id",
            type=int,
            default=self.PROVIDER_ID,
            help="Provider ID",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=None,
            help="Output directory for CSV files (default: src/)",
        )

    def handle(self, *args, **options):
        provider_id = options["provider_id"]
        output_dir = options.get("output_dir")

        if output_dir:
            base_path = Path(output_dir)
            self.CLASSES_CSV = base_path / "SHAMS.Class.export.csv"
            self.GROUPS_CSV = base_path / "SHAMS.Groups.export.csv"
            self.ACTIVITIES_CSV = base_path / "SHAMS.export.csv"

        try:
            provider = Provider.objects.get(id=provider_id)
        except Provider.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Provider {provider_id} not found"))
            return

        self.stdout.write(f"Provider: {provider.title_en} (ID: {provider.id})")
        self.stdout.write("")

        # Export classes
        classes_count = self._export_classes(provider)
        self.stdout.write(f"✓ Classes exported: {classes_count} records → {self.CLASSES_CSV}")

        # Export groups
        groups_count = self._export_groups(provider)
        self.stdout.write(f"✓ Groups exported: {groups_count} records → {self.GROUPS_CSV}")

        # Export activities
        activities_count = self._export_activities(provider)
        self.stdout.write(f"✓ Activities exported: {activities_count} records → {self.ACTIVITIES_CSV}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Export completed"))
        self.stdout.write("")

        # Print DDL
        self._print_ddl()

    def _export_classes(self, provider):
        classes = ProviderActivityTypeClass.objects.filter(provider=provider).order_by("code")

        with open(self.CLASSES_CSV, "w", encoding="utf-8", newline="") as csvfile:
            fieldnames = ["ID", "Class code", "Class name en", "Class name ru"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for cls in classes:
                writer.writerow(
                    {
                        "ID": cls.id,
                        "Class code": cls.code or "",
                        "Class name en": cls.title_en or "",
                        "Class name ru": cls.title_ru or "",
                    }
                )

        return classes.count()

    def _export_groups(self, provider):
        groups = ProviderActivityTypeGroup.objects.filter(provider=provider).order_by("code")

        with open(self.GROUPS_CSV, "w", encoding="utf-8", newline="") as csvfile:
            fieldnames = ["ID", "Group code", "Group name en", "Group name ru"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for group in groups:
                writer.writerow(
                    {
                        "ID": group.id,
                        "Group code": group.code or "",
                        "Group name en": group.title_en or "",
                        "Group name ru": group.title_ru or "",
                    }
                )

        return groups.count()

    def _export_activities(self, provider):
        activities = (
            ProviderActivityType.objects.filter(provider=provider)
            .select_related(
                "business_activity",
                "activity_type_group",
                "activity_type_class",
                "license_type",
            )
            .prefetch_related(
                "packages",
                "infrastructure_facilities_are_required",
                "who_can_be_founder",
                "possible_legal_form",
                "additional_permissions",
            )
            .order_by("business_activity_code")
        )

        fieldnames = [
            "ID",
            "Официальное Наименование бизнес-деятельности у провайдера en",
            "Официальное Наименование бизнес-деятельности у провайдера ru",
            "Введите код бизнес-деятельности",
            "Выберите группу",
            "Выберите класс",
            "ИД Универсальное наименование бизнес-деятельности",
            "Тип лицензии",
            "Приоритет",
            "Описание вида деятельности en (=ПУСТО)",
            "Описание вида деятельности ru (=ПУСТО)",
            "Примечание (для внутреннего использования)",
            "Дополнительные требования, условия ",
            "Нужны дополнительные разрешения (NOC)",
            "Существуют специальные требования к уставному капиталу",
            "Существуют специальные требования к инфраструктуре",
            "Существуют специальные требования к учредителю",
            "Можно совмещать с другими активити",
            "Деятельность только на территории страны регистрации",
            "Деятельность только за пределами страны регистрации",
            "Только для филиалов иностранных компаний",
            "Существуют дополнительные требования, условия",
            "Пакеты",
            "Требуется наличие инфраструктурных объектов",
            "Кто может быть учредителем",
            "Специальные требования к уставному капиталу",
            "ОПФ",
            "1. ИД органа",
            "1. ИД Услуги",
            "2. ИД органа",
            "2. ИД Услуги",
            "3. ИД органа",
            "3. ИД Услуги",
        ]

        with open(self.ACTIVITIES_CSV, "w", encoding="utf-8", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for activity in activities:
                # Parse note to extract additional requirements
                note = activity.note or ""
                additional_requirements = ""
                internal_note = ""

                if note:
                    if "\n\nДополнительные требования: " in note:
                        parts = note.split("\n\nДополнительные требования: ", 1)
                        internal_note = parts[0]
                        additional_requirements = parts[1]
                    elif note.startswith("Дополнительные требования: "):
                        additional_requirements = note.replace("Дополнительные требования: ", "", 1)
                    else:
                        internal_note = note

                # Get permissions
                permissions = list(activity.additional_permissions.all().select_related("authority", "service")[:3])
                permission_1_authority = (
                    permissions[0].authority.id if len(permissions) > 0 and permissions[0].authority else ""
                )
                permission_1_service = (
                    permissions[0].service.id if len(permissions) > 0 and permissions[0].service else ""
                )
                permission_2_authority = (
                    permissions[1].authority.id if len(permissions) > 1 and permissions[1].authority else ""
                )
                permission_2_service = (
                    permissions[1].service.id if len(permissions) > 1 and permissions[1].service else ""
                )
                permission_3_authority = (
                    permissions[2].authority.id if len(permissions) > 2 and permissions[2].authority else ""
                )
                permission_3_service = (
                    permissions[2].service.id if len(permissions) > 2 and permissions[2].service else ""
                )

                writer.writerow(
                    {
                        "ID": activity.id,
                        "Официальное Наименование бизнес-деятельности у провайдера en": activity.title_by_provider_en
                        or "",
                        "Официальное Наименование бизнес-деятельности у провайдера ru": activity.title_by_provider_ru
                        or "",
                        "Введите код бизнес-деятельности": activity.business_activity_code or "",
                        "Выберите группу": activity.activity_type_group.code if activity.activity_type_group else "",
                        "Выберите класс": activity.activity_type_class.code if activity.activity_type_class else "",
                        "ИД Универсальное наименование бизнес-деятельности": activity.business_activity.id
                        if activity.business_activity
                        else "",
                        "Тип лицензии": activity.license_type.id if activity.license_type else "",
                        "Приоритет": activity.priority if activity.priority else "",
                        "Описание вида деятельности en (=ПУСТО)": activity.description_en or "",
                        "Описание вида деятельности ru (=ПУСТО)": activity.description_ru or "",
                        "Примечание (для внутреннего использования)": internal_note,
                        "Дополнительные требования, условия ": additional_requirements,
                        "Нужны дополнительные разрешения (NOC)": self._format_bool(
                            activity.need_additional_permissions
                        ),
                        "Существуют специальные требования к уставному капиталу": self._format_bool(
                            activity.requirements_for_authorized_capital
                        ),
                        "Существуют специальные требования к инфраструктуре": self._format_bool(
                            activity.there_are_special_requirements_for_infrastructure
                        ),
                        "Существуют специальные требования к учредителю": self._format_bool(
                            activity.there_are_special_requirements_for_founder
                        ),
                        "Можно совмещать с другими активити": self._format_bool(
                            activity.can_be_combined_with_other_activities
                        ),
                        "Деятельность только на территории страны регистрации": self._format_bool(
                            activity.activities_only_within_territory_of_country_of_registration
                        ),
                        "Деятельность только за пределами страны регистрации": self._format_bool(
                            activity.activities_only_outside_country_of_registration
                        ),
                        "Только для филиалов иностранных компаний": self._format_bool(
                            activity.for_branches_of_foreign_companies_only
                        ),
                        "Существуют дополнительные требования, условия": self._format_bool(
                            activity.there_are_additional_requirements
                        ),
                        "Пакеты": self._format_id_list(activity.packages.all()),
                        "Требуется наличие инфраструктурных объектов": self._format_id_list(
                            activity.infrastructure_facilities_are_required.all()
                        ),
                        "Кто может быть учредителем": self._format_id_list(activity.who_can_be_founder.all()),
                        "Специальные требования к уставному капиталу": "",  # This is a text field that was not stored separately in import
                        "ОПФ": self._format_id_list(activity.possible_legal_form.all()),
                        "1. ИД органа": permission_1_authority,
                        "1. ИД Услуги": permission_1_service,
                        "2. ИД органа": permission_2_authority,
                        "2. ИД Услуги": permission_2_service,
                        "3. ИД органа": permission_3_authority,
                        "3. ИД Услуги": permission_3_service,
                    }
                )

        return activities.count()

    @staticmethod
    def _format_bool(value):
        return "TRUE" if value else ""

    @staticmethod
    def _format_id_list(queryset):
        ids = [str(obj.id) for obj in queryset]
        return "; ".join(ids) if ids else ""

    def _print_ddl(self):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write(self.style.SUCCESS("DATABASE DDL (Table Definitions)"))
        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write("")

        table_names = [
            "provider_activity_type_class",
            "provider_activity_type_group",
            "provider_activity_type",
            "provider_activity_type_permission",
        ]

        with connection.cursor() as cursor:
            for table_name in table_names:
                self.stdout.write(self.style.WARNING(f"-- Table: {table_name}"))
                self.stdout.write("")

                # Get table DDL using MySQL/PostgreSQL specific commands
                if connection.vendor == "postgresql":
                    # PostgreSQL: Get table structure
                    cursor.execute(
                        """
                        SELECT
                            'CREATE TABLE ' || quote_ident(table_name) || ' (' ||
                            string_agg(
                                quote_ident(column_name) || ' ' ||
                                CASE
                                    WHEN data_type = 'character varying' THEN 'VARCHAR(' || character_maximum_length || ')'
                                    WHEN data_type = 'character' THEN 'CHAR(' || character_maximum_length || ')'
                                    ELSE UPPER(data_type)
                                END ||
                                CASE WHEN is_nullable = 'NO' THEN ' NOT NULL' ELSE '' END,
                                ', '
                            ) ||
                            ');' as ddl
                        FROM information_schema.columns
                        WHERE table_name = %s
                        GROUP BY table_name;
                    """,
                        [table_name],
                    )
                    result = cursor.fetchone()
                    if result:
                        self.stdout.write(result[0])
                        self.stdout.write("")

                        # Get indexes
                        cursor.execute(
                            """
                            SELECT indexdef || ';'
                            FROM pg_indexes
                            WHERE tablename = %s;
                        """,
                            [table_name],
                        )
                        indexes = cursor.fetchall()
                        if indexes:
                            for idx in indexes:
                                self.stdout.write(idx[0])
                            self.stdout.write("")

                        # Get foreign keys
                        cursor.execute(
                            """
                            SELECT
                                'ALTER TABLE ' || quote_ident(tc.table_name) ||
                                ' ADD CONSTRAINT ' || quote_ident(tc.constraint_name) ||
                                ' FOREIGN KEY (' || quote_ident(kcu.column_name) || ')' ||
                                ' REFERENCES ' || quote_ident(ccu.table_name) ||
                                ' (' || quote_ident(ccu.column_name) || ')' ||
                                CASE
                                    WHEN rc.delete_rule != 'NO ACTION' THEN ' ON DELETE ' || rc.delete_rule
                                    ELSE ''
                                END || ';'
                            FROM information_schema.table_constraints AS tc
                            JOIN information_schema.key_column_usage AS kcu
                              ON tc.constraint_name = kcu.constraint_name
                              AND tc.table_schema = kcu.table_schema
                            JOIN information_schema.constraint_column_usage AS ccu
                              ON ccu.constraint_name = tc.constraint_name
                              AND ccu.table_schema = tc.table_schema
                            JOIN information_schema.referential_constraints AS rc
                              ON tc.constraint_name = rc.constraint_name
                            WHERE tc.constraint_type = 'FOREIGN KEY'
                              AND tc.table_name = %s;
                        """,
                            [table_name],
                        )
                        fks = cursor.fetchall()
                        if fks:
                            for fk in fks:
                                self.stdout.write(fk[0])
                            self.stdout.write("")

                elif connection.vendor == "mysql":
                    # MySQL: Use SHOW CREATE TABLE
                    cursor.execute(f"SHOW CREATE TABLE {table_name};")
                    result = cursor.fetchone()
                    if result and len(result) > 1:
                        self.stdout.write(result[1])
                        self.stdout.write("")

                else:
                    # Generic fallback
                    cursor.execute(
                        f"""
                        SELECT sql
                        FROM sqlite_master
                        WHERE type='table' AND name='{table_name}';
                    """
                    )
                    result = cursor.fetchone()
                    if result:
                        self.stdout.write(result[0])
                        self.stdout.write("")

                self.stdout.write("-" * 80)
                self.stdout.write("")

        self.stdout.write(self.style.SUCCESS("=" * 80))
