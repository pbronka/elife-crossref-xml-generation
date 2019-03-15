import time
import os
from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement, Comment
from xml.dom import minidom

from elifearticle import utils as eautils
from elifearticle.article import Article, Component
from elifearticle import parse
from elifetools import utils as etoolsutils
from elifetools import xmlio

from elifecrossref import utils, elife, contributor, funding
from elifecrossref.conf import raw_config, parse_raw_config
from elifecrossref.mime_type import crossref_mime_type
from elifecrossref.tags import REPARSING_NAMESPACES, add_clean_tag, add_inline_tag, clean_tags


TMP_DIR = 'tmp'


class CrossrefXML(object):

    def __init__(self, poa_articles, crossref_config, pub_date=None, add_comment=True):
        """
        Initialise the configuration, set the root node
        set default values for dates and batch id
        then build out the XML using the article objects
        """
        # Set the config
        self.crossref_config = crossref_config
        # Create the root XML node
        self.root = Element('doi_batch')
        set_root(self.root, self.crossref_config.get('crossref_schema_version'))

        # Publication date
        if pub_date is None:
            self.pub_date = time.gmtime()
        else:
            self.pub_date = pub_date

        # Generate batch id
        batch_doi = ''
        if poa_articles:
            # If only one article is supplied, then add the doi to the batch file name
            batch_doi = str(utils.clean_string(poa_articles[0].manuscript)) + '-'
        self.batch_id = (str(self.crossref_config.get('batch_file_prefix')) + batch_doi +
                         time.strftime("%Y%m%d%H%M%S", self.pub_date))

        # set comment
        if add_comment:
            self.generated = time.strftime("%Y-%m-%d %H:%M:%S")
            last_commit = eautils.get_last_commit_to_master()
            comment = Comment('generated by ' + str(crossref_config.get('generator')) +
                              ' at ' + self.generated +
                              ' from version ' + last_commit)
            self.root.append(comment)

        # to keep track of the rel:program tag, if used
        self.relations_program_tag = None

        # Build out the Crossref XML
        self.build(poa_articles)

    def build(self, poa_articles):
        self.set_head(self.root)
        self.set_body(self.root, poa_articles)

    def set_head(self, parent):
        head_tag = SubElement(parent, 'head')
        doi_batch_id_tag = SubElement(head_tag, 'doi_batch_id')
        doi_batch_id_tag.text = self.batch_id
        timestamp_tag = SubElement(head_tag, 'timestamp')
        timestamp_tag.text = time.strftime("%Y%m%d%H%M%S", self.pub_date)
        self.set_depositor(head_tag)
        registrant_tag = SubElement(head_tag, 'registrant')
        registrant_tag.text = self.crossref_config.get("registrant")

    def set_depositor(self, parent):
        depositor_tag = SubElement(parent, 'depositor')
        name_tag = SubElement(depositor_tag, 'depositor_name')
        name_tag.text = self.crossref_config.get("depositor_name")
        email_address_tag = SubElement(depositor_tag, 'email_address')
        email_address_tag.text = self.crossref_config.get("email_address")

    def set_body(self, parent, poa_articles):
        body_tag = SubElement(parent, 'body')

        for poa_article in poa_articles:
            # Create a new journal record for each article
            self.set_journal(body_tag, poa_article)

    def get_pub_date(self, poa_article):
        """
        For using in XML generation, use the article pub date
        or by default use the run time pub date
        """
        pub_date = None

        for date_type in self.crossref_config.get('pub_date_types'):
            pub_date_obj = poa_article.get_date(date_type)
            if pub_date_obj:
                break

        if pub_date_obj:
            pub_date = pub_date_obj.date
        else:
            # Default use the run time date
            pub_date = self.pub_date
        return pub_date

    def set_journal(self, parent, poa_article):
        # Add journal for each article
        journal_tag = SubElement(parent, 'journal')
        set_journal_metadata(journal_tag, poa_article)

        journal_issue_tag = SubElement(journal_tag, 'journal_issue')

        pub_date = self.get_pub_date(poa_article)
        set_publication_date(journal_issue_tag, pub_date)

        journal_volume_tag = SubElement(journal_issue_tag, 'journal_volume')
        volume_tag = SubElement(journal_volume_tag, 'volume')
        # Use volume from the article unless not present then use the default
        if poa_article.volume:
            volume_tag.text = poa_article.volume
        else:
            if self.crossref_config.get("year_of_first_volume"):
                volume_tag.text = eautils.calculate_journal_volume(
                    pub_date, self.crossref_config.get("year_of_first_volume"))

        # Add journal article
        self.set_journal_article(journal_tag, poa_article)

    def set_journal_article(self, parent, poa_article):
        journal_article_tag = SubElement(parent, 'journal_article')
        journal_article_tag.set("publication_type", "full_text")
        if (self.crossref_config.get("reference_distribution_opts")
                and self.crossref_config.get("reference_distribution_opts") != ''):
            journal_article_tag.set(
                "reference_distribution_opts",
                self.crossref_config.get("reference_distribution_opts"))

        # Set the title with italic tag support
        self.set_titles(journal_article_tag, poa_article)

        contributor.set_contributors(journal_article_tag, poa_article,
                                     self.crossref_config.get("contrib_types"))

        self.set_abstract(journal_article_tag, poa_article)
        self.set_digest(journal_article_tag, poa_article)

        # Journal publication date
        pub_date = self.get_pub_date(poa_article)
        set_publication_date(journal_article_tag, pub_date)

        publisher_item_tag = SubElement(journal_article_tag, 'publisher_item')
        if self.crossref_config.get("elocation_id") and poa_article.elocation_id:
            item_number_tag = SubElement(publisher_item_tag, 'item_number')
            item_number_tag.set("item_number_type", "article_number")
            item_number_tag.text = poa_article.elocation_id
        identifier_tag = SubElement(publisher_item_tag, 'identifier')
        identifier_tag.set("id_type", "doi")
        identifier_tag.text = poa_article.doi

        # Disable crossmark for now
        # self.set_crossmark(self.journal_article, poa_article)

        funding.set_fundref(journal_article_tag, poa_article)

        self.set_access_indicators(journal_article_tag, poa_article)

        # this is the spot to add the relations program tag if it is required
        if do_relations_program(poa_article) is True:
            self.set_relations_program(journal_article_tag)

        self.set_datasets(journal_article_tag, poa_article)

        set_archive_locations(journal_article_tag,
                              self.crossref_config.get("archive_locations"))

        self.set_doi_data(journal_article_tag, poa_article)

        self.set_citation_list(journal_article_tag, poa_article)

        self.set_component_list(journal_article_tag, poa_article)

    def set_titles(self, parent, poa_article):
        """
        Set the titles and title tags allowing sub tags within title
        """
        root_tag_name = 'titles'
        tag_name = 'title'
        root_xml_element = Element(root_tag_name)
        # remove unwanted tags
        tag_converted_title = eautils.remove_tag('ext-link', poa_article.title)
        if self.crossref_config.get('face_markup') is True:
            add_inline_tag(root_xml_element, tag_name, tag_converted_title)
        else:
            add_clean_tag(root_xml_element, tag_name, tag_converted_title)
        parent.append(root_xml_element)

    def set_doi_data(self, parent, poa_article):
        doi_data_tag = SubElement(parent, 'doi_data')

        doi_tag = SubElement(doi_data_tag, 'doi')
        doi_tag.text = poa_article.doi

        resource_tag = SubElement(doi_data_tag, 'resource')

        resource = self.generate_resource_url(poa_article, poa_article)
        resource_tag.text = resource

        self.set_collection(doi_data_tag, poa_article, "text-mining")

    def set_collection(self, parent, poa_article, collection_property):
        if self.do_set_collection(poa_article, collection_property):
            if collection_property == "text-mining":
                collection_tag = SubElement(parent, 'collection')
                collection_tag.set("property", collection_property)
                if self.do_set_collection_text_mining_pdf(poa_article) is True:
                    item_tag = SubElement(collection_tag, 'item')
                    resource_tag = SubElement(item_tag, 'resource')
                    resource_tag.set("mime_type", "application/pdf")
                    resource_tag.text = self.generate_resource_url(
                        poa_article, poa_article, "text_mining_pdf_pattern")
                if self.do_set_collection_text_mining_xml() is True:
                    item_tag = SubElement(collection_tag, 'item')
                    resource_tag = SubElement(item_tag, 'resource')
                    resource_tag.set("mime_type", "application/xml")
                    resource_tag.text = self.generate_resource_url(
                        poa_article, poa_article, "text_mining_xml_pattern")

    def do_set_collection_text_mining_xml(self):
        """decide whether to text mining xml resource"""
        if (self.crossref_config.get("text_mining_xml_pattern")
                and self.crossref_config.get("text_mining_pdf_pattern") != ''):
            return True
        return False

    def do_set_collection_text_mining_pdf(self, poa_article):
        """decide whether to text mining pdf resource"""
        if (self.crossref_config.get("text_mining_pdf_pattern")
                and self.crossref_config.get("text_mining_pdf_pattern") != ''
                and poa_article.get_self_uri("pdf") is not None):
            return True
        return False

    def do_set_collection(self, poa_article, collection_property):
        """decide whether to set collection tags"""
        # only add text and data mining details if the article has a license
        if not has_license(poa_article):
            return False
        if collection_property == "text-mining":
            if (self.do_set_collection_text_mining_xml() is True
                    or self.do_set_collection_text_mining_pdf(poa_article) is True):
                return True
        return False

    def generate_resource_url(self, obj, poa_article, pattern_type=None):
        # Generate a resource value for doi_data based on the object provided
        if isinstance(obj, Article):
            if not pattern_type:
                pattern_type = "doi_pattern"
            version = elife.elife_style_article_attributes(obj)
            doi_pattern = self.crossref_config.get(pattern_type)
            if doi_pattern != '':
                return self.crossref_config.get(pattern_type).format(
                    doi=obj.doi,
                    manuscript=obj.manuscript,
                    volume=obj.volume,
                    version=version)
            else:
                # if no doi_pattern is specified, try to get it from the self-uri value
                #  that has no content_type
                for self_uri in obj.self_uri_list:
                    if self_uri.content_type is None:
                        return self_uri.xlink_href

        elif isinstance(obj, Component):
            component_id = obj.id
            prefix1 = ''
            if self.crossref_config.get('elife_style_component_doi') is True:
                component_id, prefix1 = elife.elife_style_component_attributes(obj)
            return self.crossref_config.get("component_doi_pattern").format(
                doi=poa_article.doi,
                manuscript=poa_article.manuscript,
                volume=poa_article.volume,
                prefix1=prefix1,
                id=component_id)
        return None

    def set_abstract(self, parent, poa_article):
        if poa_article.abstract:
            abstract = poa_article.abstract
            self.set_abstract_tag(parent, abstract, abstract_type="abstract")

    def set_digest(self, parent, poa_article):
        if hasattr(poa_article, 'digest') and poa_article.digest:
            self.set_abstract_tag(parent, poa_article.digest, abstract_type="executive-summary")

    def set_abstract_tag(self, parent, abstract, abstract_type):

        tag_name = 'jats:abstract'

        attributes = []
        attributes_text = ''
        if abstract_type == 'executive-summary':
            attributes = ['abstract-type']
            attributes_text = ' abstract-type="executive-summary" '

        # Convert the abstract to jats abstract tags, or strip all the inline tags
        if self.crossref_config.get('jats_abstract') is True:
            tag_converted_abstract = abstract
            tag_converted_abstract = etoolsutils.escape_ampersand(tag_converted_abstract)
            tag_converted_abstract = etoolsutils.escape_unmatched_angle_brackets(
                tag_converted_abstract, utils.allowed_tags())
            tag_converted_abstract = eautils.replace_tags(
                tag_converted_abstract, 'p', 'jats:p')
            tag_converted_abstract = eautils.replace_tags(
                tag_converted_abstract, 'italic', 'jats:italic')
            tag_converted_abstract = eautils.replace_tags(
                tag_converted_abstract, 'bold', 'jats:bold')
            tag_converted_abstract = eautils.replace_tags(
                tag_converted_abstract, 'underline', 'jats:underline')
            tag_converted_abstract = eautils.replace_tags(
                tag_converted_abstract, 'sub', 'jats:sub')
            tag_converted_abstract = eautils.replace_tags(
                tag_converted_abstract, 'sup', 'jats:sup')
            tag_converted_abstract = eautils.replace_tags(
                tag_converted_abstract, 'sc', 'jats:sc')
            tag_converted_abstract = eautils.remove_tag('inline-formula', tag_converted_abstract)
            tag_converted_abstract = eautils.remove_tag('ext-link', tag_converted_abstract)
        else:
            # Strip inline tags, keep the p tags
            tag_converted_abstract = abstract
            tag_converted_abstract = etoolsutils.escape_ampersand(tag_converted_abstract)
            tag_converted_abstract = etoolsutils.escape_unmatched_angle_brackets(
                tag_converted_abstract, utils.allowed_tags())
            tag_converted_abstract = clean_tags(
                tag_converted_abstract, do_not_clean=['<p>', '</p>', '<mml:', '</mml:'])
            tag_converted_abstract = eautils.replace_tags(tag_converted_abstract, 'p', 'jats:p')
            tag_converted_abstract = tag_converted_abstract

        tagged_string = '<' + tag_name + REPARSING_NAMESPACES + attributes_text + '>'
        tagged_string += tag_converted_abstract
        tagged_string += '</' + tag_name + '>'
        reparsed = minidom.parseString(tagged_string.encode('utf-8'))

        recursive = False
        xmlio.append_minidom_xml_to_elementtree_xml(parent, reparsed, recursive, attributes)

    def set_access_indicators(self, parent, poa_article):
        """
        Set the AccessIndicators
        """

        applies_to = self.crossref_config.get("access_indicators_applies_to")

        if applies_to and has_license(poa_article) is True:

            ai_program_tag = SubElement(parent, 'ai:program')
            ai_program_tag.set('name', 'AccessIndicators')

            for applies_to in applies_to:
                ai_program_ref_tag = SubElement(ai_program_tag, 'ai:license_ref')
                ai_program_ref_tag.set('applies_to', applies_to)
                ai_program_ref_tag.text = poa_article.license.href

    def set_citation_list(self, parent, poa_article):
        """
        Set the citation_list from the article object ref_list objects
        """
        ref_index = 0
        if poa_article.ref_list:
            citation_list_tag = SubElement(parent, 'citation_list')
        for ref in poa_article.ref_list:
            # Increment
            ref_index = ref_index + 1
            # decide whether to create a related_item for the citation
            if do_citation_related_item(ref):
                # first set the parent tag if it does not yet exist
                self.set_citation_related_item(parent, ref)

            # continue with creating a citation tag
            set_citation(citation_list_tag, ref, ref_index,
                         self.crossref_config.get('face_markup'),
                         self.crossref_config.get('crossref_schema_version'))

    def set_citation_related_item(self, parent, ref):
        """depends on the relations_program tag existing already"""
        # first set the parent tag if it does not yet exist
        self.set_relations_program(parent)
        related_item_tag = SubElement(self.relations_program_tag, 'rel:related_item')
        if ref.data_title:
            set_related_item_description(related_item_tag, ref.data_title)
        identifier_type = None
        related_item_text = None
        related_item_type = "inter_work_relation"
        relationship_type = "references"
        if ref.doi:
            identifier_type = "doi"
            related_item_text = ref.doi
        elif ref.accession:
            identifier_type = "accession"
            related_item_text = ref.accession
        elif ref.pmid:
            identifier_type = "pmid"
            related_item_text = ref.pmid
        elif ref.uri:
            identifier_type = "uri"
            related_item_text = ref.uri
        if identifier_type and related_item_text:
            set_related_item_work_relation(
                related_item_tag, related_item_type, relationship_type,
                identifier_type, related_item_text)

    def set_relations_program(self, parent):
        """set the relations program parent tag only once"""
        if self.relations_program_tag is None:
            self.relations_program_tag = SubElement(parent, 'rel:program')

    def set_datasets(self, parent, poa_article):
        """
        Add related_item tags for each dataset
        """
        for dataset in poa_article.datasets:
            # Check for at least one identifier before adding the related_item
            if not do_dataset_related_item(dataset):
                continue
            # first set the parent tag if it does not yet exist
            self.set_relations_program(parent)
            # add related_item tag
            related_item_tag = SubElement(self.relations_program_tag, 'rel:related_item')
            related_item_type = "inter_work_relation"
            description = None
            relationship_type = dataset_relationship_type(dataset)
            # set the description
            if dataset.title:
                description = dataset.title
            if description:
                set_related_item_description(related_item_tag, description)
            # Now add one inter_work_relation tag in order ot priority
            if dataset.doi:
                identifier_type = "doi"
                related_item_text = dataset.doi
                set_related_item_work_relation(
                    related_item_tag, related_item_type, relationship_type,
                    identifier_type, related_item_text)
            elif dataset.accession_id:
                identifier_type = "accession"
                related_item_text = dataset.accession_id
                set_related_item_work_relation(
                    related_item_tag, related_item_type, relationship_type,
                    identifier_type, related_item_text)
            elif dataset.uri:
                identifier_type = "uri"
                related_item_text = dataset.uri
                set_related_item_work_relation(
                    related_item_tag, related_item_type, relationship_type,
                    identifier_type, related_item_text)

    def set_component_list(self, parent, poa_article):
        """
        Set the component_list from the article object component_list objects
        """
        if not poa_article.component_list:
            return

        component_list_tag = SubElement(parent, 'component_list')
        for comp in poa_article.component_list:
            component_tag = SubElement(component_list_tag, 'component')
            component_tag.set("parent_relation", "isPartOf")

            titles_tag = SubElement(component_tag, 'titles')

            title_tag = SubElement(titles_tag, 'title')
            title_tag.text = comp.title

            if comp.subtitle:
                self.set_subtitle(titles_tag, comp)

            if comp.mime_type:
                # Convert to allowed mime types for Crossref, if found
                if crossref_mime_type(comp.mime_type):
                    format_tag = SubElement(component_tag, 'format')
                    format_tag.set("mime_type", crossref_mime_type(comp.mime_type))

            if comp.permissions:
                self.set_component_permissions(component_tag, comp.permissions)

            if comp.doi:
                # Try generating a resource value then continue
                resource_url = self.generate_resource_url(comp, poa_article)
                if resource_url and resource_url != '':
                    doi_data_tag = SubElement(component_tag, 'doi_data')
                    doi_tag_tag = SubElement(doi_data_tag, 'doi')
                    doi_tag_tag.text = comp.doi
                    resource_tag = SubElement(doi_data_tag, 'resource')
                    resource_tag.text = resource_url

    def set_component_permissions(self, parent, permissions):
        """Specific license for the component"""
        # First check if a license ref is in the config
        if self.crossref_config.get('component_license_ref') != '':
            # set the component permissions if it has any copyright statement or license value
            set_permissions = False
            for permission in permissions:
                if permission.get('copyright_statement') or permission.get('license'):
                    set_permissions = True
            if set_permissions is True:
                component_ai_program_tag = SubElement(parent, 'ai:program')
                component_ai_program_tag.set('name', 'AccessIndicators')
                license_ref_tag = SubElement(component_ai_program_tag, 'ai:license_ref')
                license_ref_tag.text = self.crossref_config.get('component_license_ref')

    def set_subtitle(self, parent, component):
        tag_name = 'subtitle'
        # Use <i> tags, not <italic> tags, <b> tags not <bold>
        if component.subtitle:
            if self.crossref_config.get('face_markup') is True:
                add_inline_tag(parent, tag_name, component.subtitle)
            else:
                add_clean_tag(parent, tag_name, component.subtitle)

    def output_xml(self, pretty=False, indent=""):
        encoding = 'utf-8'

        rough_string = ElementTree.tostring(self.root, encoding)
        reparsed = minidom.parseString(rough_string)

        if pretty is True:
            return reparsed.toprettyxml(indent, encoding=encoding).decode(encoding)
        return reparsed.toxml(encoding=encoding).decode(encoding)


def set_root(root, schema_version):
    """Set the root tag namespaces and schema details

    :param root: ElementTree.Element tag
    :param schema_version: version of the Crossref schema as a string, e.g. 4.4.1
    """
    root.set('version', schema_version)
    root.set('xmlns', 'http://www.crossref.org/schema/%s' % schema_version)
    root.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')
    root.set('xmlns:fr', 'http://www.crossref.org/fundref.xsd')
    root.set('xmlns:ai', 'http://www.crossref.org/AccessIndicators.xsd')
    if schema_version != "4.3.5":
        root.set('xmlns:ct', 'http://www.crossref.org/clinicaltrials.xsd')
        root.set('xmlns:rel', 'http://www.crossref.org/relations.xsd')
    schema_location_name = 'http://www.crossref.org/schema/%s' % schema_version
    schema_location_uri = 'http://www.crossref.org/schemas/crossref%s.xsd' % schema_version
    root.set('xsi:schemaLocation', '%s %s' % (schema_location_name, schema_location_uri))
    root.set('xmlns:mml', 'http://www.w3.org/1998/Math/MathML')
    root.set('xmlns:jats', 'http://www.ncbi.nlm.nih.gov/JATS1')


def set_citation(parent, ref, ref_index, face_markup,
                 crossref_schema_version):
    # continue with creating a citation tag
    citation_tag = SubElement(parent, 'citation')

    if ref.id:
        citation_tag.set("key", ref.id)
    else:
        citation_tag.set("key", str(ref_index))

    if ref.source:
        if ref.publication_type == "journal":
            journal_title_tag = SubElement(citation_tag, 'journal_title')
            journal_title_tag.text = ref.source
        else:
            volume_title_tag = SubElement(citation_tag, 'volume_title')
            volume_title_tag.text = ref.source

    authors = filter_citation_authors(ref)
    if authors:
        # Only set the first author surname
        first_author = authors[0]
        if first_author.get("surname"):
            author_tag = SubElement(citation_tag, 'author')
            author_tag.text = first_author.get("surname")
        elif first_author.get("collab"):
            add_clean_tag(citation_tag, 'author', first_author.get("collab"))

    if ref.volume:
        volume_tag = SubElement(citation_tag, 'volume')
        volume_tag.text = ref.volume[0:31]

    if ref.issue:
        issue_tag = SubElement(citation_tag, 'issue')
        issue_tag.text = ref.issue

    if ref.fpage:
        first_page_tag = SubElement(citation_tag, 'first_page')
        first_page_tag.text = ref.fpage

    if ref.year or ref.year_numeric:
        cyear_tag = SubElement(citation_tag, 'cYear')
        # Prefer the numeric year value if available
        if ref.year_numeric:
            cyear_tag.text = str(ref.year_numeric)
        else:
            cyear_tag.text = ref.year

    if ref.article_title or ref.data_title:
        if ref.article_title:
            add_clean_tag(citation_tag, 'article_title', ref.article_title)
        elif ref.data_title:
            add_clean_tag(citation_tag, 'article_title', ref.data_title)

    if ref.doi:
        doi_tag = SubElement(citation_tag, 'doi')
        doi_tag.text = ref.doi

    if ref.isbn:
        isbn_tag = SubElement(citation_tag, 'isbn')
        isbn_tag.text = ref.isbn

    if ref.elocation_id:
        if crossref_schema_version in ['4.3.5', '4.3.7', '4.4.0']:
            # Until alternate tag is available, elocation-id goes into first_page tag
            first_page_tag = SubElement(citation_tag, 'first_page')
            first_page_tag.text = ref.elocation_id
        else:
            # schema greater than 4.4.0 supports elocation_id
            elocation_id_tag = SubElement(citation_tag, 'elocation_id')
            elocation_id_tag.text = ref.elocation_id

    # unstructured-citation
    if do_unstructured_citation(ref) is True:
        set_unstructured_citation(citation_tag, ref, face_markup)


def set_unstructured_citation(parent, ref, face_markup):
    # tag_content
    tag_content = ''
    author_line = citation_author_line(ref)

    if ref.publication_type and ref.publication_type in [
            'confproc', 'patent', 'preprint', 'report', 'software', 'thesis', 'web', 'webpage']:
        tag_content = '. '.join([item.rstrip('.') for item in [
            author_line, ref.year, ref.article_title, ref.data_title,
            citation_publisher(ref), ref.source, ref.version,
            ref.patent, ref.conf_name, citation_uri(ref)] if item is not None])
        tag_content += '.'
    # add the tag if there is tag_content
    if tag_content != '':
        # handle inline tagging
        if face_markup is True:
            add_inline_tag(parent, 'unstructured_citation', tag_content)
        else:
            add_clean_tag(parent, 'unstructured_citation', tag_content)
    return parent


def set_journal_metadata(parent, poa_article):
    # journal_metadata
    journal_metadata_tag = SubElement(parent, 'journal_metadata')
    journal_metadata_tag.set("language", "en")
    full_title_tag = SubElement(journal_metadata_tag, 'full_title')
    full_title_tag.text = poa_article.journal_title
    issn_tag = SubElement(journal_metadata_tag, 'issn')
    issn_tag.set("media_type", "electronic")
    issn_tag.text = poa_article.journal_issn


def has_license(poa_article):
    """check if the article has the minimum requirements of a license"""
    if not poa_article.license:
        return False
    if not poa_article.license.href:
        return False
    return True


def set_publication_date(parent, pub_date):
    # pub_date is a python time object
    if pub_date:
        publication_date_tag = SubElement(parent, 'publication_date')
        publication_date_tag.set("media_type", "online")
        month_tag = SubElement(publication_date_tag, "month")
        month_tag.text = str(pub_date.tm_mon).zfill(2)
        day_tag = SubElement(publication_date_tag, "day")
        day_tag.text = str(pub_date.tm_mday).zfill(2)
        year_tag = SubElement(publication_date_tag, "year")
        year_tag.text = str(pub_date.tm_year)


def set_archive_locations(parent, archive_locations):
    if archive_locations:
        archive_locations_tag = SubElement(parent, 'archive_locations')
        for archive_location in archive_locations:
            archive_tag = SubElement(archive_locations_tag, 'archive')
            archive_tag.set('name', archive_location)


def filter_citation_authors(ref):
    """logic for which authors to select for citation records"""
    # First consider authors with group-type author
    authors = [c for c in ref.authors if c.get('group-type') == 'author']
    if not authors:
        # Take editors if there are no authors
        authors = [c for c in ref.authors if c.get('group-type') == 'editor']
    return authors


def do_unstructured_citation(ref):
    """decide if a citation should have an unstructured_citation tag added"""
    if ref.publication_type and ref.publication_type in [
            'confproc', 'patent', 'software', 'thesis', 'web', 'webpage']:
        return True
    if ref.publication_type and ref.publication_type in ['preprint'] and ref.doi is None:
        return True
    if ref.publication_type and ref.publication_type in ['report'] and ref.isbn is None:
        return True
    return False


def citation_author_line(ref):
    author_line = None
    author_names = []
    # extract all authors regardless of their group-type
    for author in ref.authors:
        author_name = ''
        if author.get('surname'):
            author_name = author.get('surname')
            if author.get('given-names'):
                author_name += ' ' + author.get('given-names')
        elif author.get('collab'):
            author_name = author.get('collab')
        if author_name != '':
            author_names.append(author_name)
    if author_names:
        author_line = ', '.join(author_names)
    return author_line


def citation_publisher(ref):
    if ref.publisher_loc or ref.publisher_name:
        return ': '.join([item for item in [
            ref.publisher_loc, ref.publisher_name] if item is not None])
    return None


def citation_uri(ref):
    uri_content = ''
    if ref.uri:
        uri_content = ref.uri
    if ref.date_in_citation:
        uri_content += ' [Accessed ' + ref.date_in_citation + ']'
    return uri_content if uri_content != '' else None


def do_citation_related_item(ref):
    """decide whether to create a related_item for a citation"""
    if ref.publication_type and ref.publication_type == "data":
        return bool(ref.doi or ref.accession or ref.pmid or ref.uri)
    return False


def do_dataset_related_item(dataset):
    """decide whether to create a related_item for a dataset"""
    return bool(dataset.accession_id or dataset.doi or dataset.uri)


def do_relations_program(poa_article):
    """call at a specific moment during generation to set this tag if required"""
    do_relations = None
    for dataset in poa_article.datasets:
        if do_dataset_related_item(dataset) is True:
            do_relations = True
            break
    if do_relations is not True and poa_article.ref_list:
        for ref in poa_article.ref_list:
            if do_citation_related_item(ref) is True:
                do_relations = True
                break
    return do_relations


def dataset_relationship_type(dataset):
    """relationship_type for the related_item depending on the dataset_type"""
    if dataset.dataset_type:
        if dataset.dataset_type == "prev_published_datasets":
            return "references"
        elif dataset.dataset_type == "datasets":
            return "isSupplementedBy"
    # default if not specified
    return "isSupplementedBy"


def set_related_item_description(parent, description):
    if description:
        description_tag = SubElement(parent, 'rel:description')
        description_tag.text = description


def set_related_item_work_relation(parent, related_item_type, relationship_type,
                                   identifier_type, related_item_text):
    # only supporting inter_work_relation for now
    if related_item_type == "inter_work_relation":
        work_relation_tag = SubElement(parent, 'rel:inter_work_relation')
        work_relation_tag.set("relationship-type", relationship_type)
        work_relation_tag.set("identifier-type", identifier_type)
        work_relation_tag.text = related_item_text


def build_crossref_xml(poa_articles, crossref_config=None, pub_date=None, add_comment=True):
    """
    Given a list of article article objects
    generate crossref XML from them
    """
    if not crossref_config:
        crossref_config = parse_raw_config(raw_config(None))
    return CrossrefXML(poa_articles, crossref_config, pub_date, add_comment)


def crossref_xml(poa_articles, crossref_config=None, pub_date=None, add_comment=True):
    """build crossref xml and return output as a string"""
    if not crossref_config:
        crossref_config = parse_raw_config(raw_config(None))
    c_xml = build_crossref_xml(poa_articles, crossref_config, pub_date, add_comment)
    return c_xml.output_xml()


def crossref_xml_to_disk(poa_articles, crossref_config=None, pub_date=None, add_comment=True):
    """build crossref xml and write the output to disk"""
    if not crossref_config:
        crossref_config = parse_raw_config(raw_config(None))
    c_xml = build_crossref_xml(poa_articles, crossref_config, pub_date, add_comment)
    xml_string = c_xml.output_xml()
    # Write to file
    filename = TMP_DIR + os.sep + c_xml.batch_id + '.xml'
    with open(filename, "wb") as open_file:
        try:
            open_file.write(xml_string.encode('utf-8'))
        except UnicodeDecodeError:  # pragma: no cover
            open_file.write(xml_string)


def build_articles_for_crossref(article_xmls, detail='full', build_parts=None):
    """specify some detail and build_parts specific to generating crossref output"""
    build_parts = [
        'abstract', 'basic', 'components', 'contributors', 'funding', 'datasets',
        'license', 'pub_dates', 'references', 'volume']
    return build_articles(article_xmls, detail, build_parts)


def build_articles(article_xmls, detail='full', build_parts=None):
    return parse.build_articles_from_article_xmls(article_xmls, detail, build_parts)
