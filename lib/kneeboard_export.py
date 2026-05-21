import os, logging, tempfile, shutil

from PIL import Image
import pymupdf

from lib.kneeboard_order import resolve_kneeboard_order

logger = logging.getLogger('html_brief_log')
logger_ui = logging.getLogger('ui_logger')

def export_kneeboards(conf, bms_conf):
    copy_to_kto = (bms_conf.theater_config[bms_conf.theater]['copy_to_kto'] == 'True')
    airframe = conf['bms']['default_airframe']
    if airframe not in {"F-16", "F-15"}:
        raise ValueError(f"Unsupported airframe for kneeboard export: {airframe}")
    output = bms_conf.theater_config[bms_conf.theater]['target_folder']
    ordered_pages, warnings = resolve_kneeboard_order(conf, airframe)
    for warning in warnings:
        logger_ui.warning(warning)
    export_pages = [page for page in ordered_pages if page.included]
    with tempfile.TemporaryDirectory() as tmp_dir:
        pages_conv = _render_export_pages(export_pages, tmp_dir)
        if airframe == "F-16":
            for i in range((len(pages_conv)+1)//2):
                if (i < 16):
                    kneeboard_name = os.path.join(output, str(7982+i) + ".dds")
                    kto_kneeboard_name = os.path.join(bms_conf.kto_target_folder, str(7982+i) + ".dds")
                    if os.path.isfile(kneeboard_name):
                        logger_ui.info(f"Backing up {kneeboard_name} to {kneeboard_name}.bkp...")
                        shutil.copyfile(kneeboard_name, kneeboard_name + ".bkp")
                    if copy_to_kto:
                        if os.path.isfile(kto_kneeboard_name):
                            logger_ui.info(f"Backing up {kto_kneeboard_name} to {kto_kneeboard_name}.bkp...")
                            shutil.copyfile(kto_kneeboard_name, kto_kneeboard_name + ".bkp")
                    if (2*i + 1) < len(pages_conv):
                        im1 = Image.open(os.path.join(tmp_dir, pages_conv[2*i])).resize((1024, 2048))
                        im2 = Image.open(os.path.join(tmp_dir, pages_conv[2*i + 1])).resize((1024, 2048))
                        im_joined = Image.new("RGBA", (2048, 2048), 'white')
                        im_joined.paste(im1)
                        im_joined.paste(im2, (im1.size[0], 0))
                        im_joined.save(kneeboard_name)
                        if copy_to_kto:
                            im_joined.save(kto_kneeboard_name)
                        im1.close()
                        im2.close()
                        im_joined.close()
                    else:
                        im1 = Image.open(os.path.join(tmp_dir, pages_conv[2*i])).resize((1024, 2048))
                        im_joined = Image.new("RGBA", (2048, 2048), 'white')
                        im_joined.paste(im1)
                        im_joined.save(kneeboard_name)
                        if copy_to_kto:
                            im_joined.save(kto_kneeboard_name)
                        im1.close()
                        im_joined.close()
                else:
                    logger_ui.info("Too many pages, stopping.")
                    break
        if airframe == "F-15":
            for i in range(len(pages_conv)):
                if (i < 16):
                    kneeboard_name = os.path.join(output, str(1403+i) + ".dds")
                    kto_kneeboard_name = os.path.join(bms_conf.kto_target_folder, str(1403+i) + ".dds")
                    if os.path.isfile(kneeboard_name):
                        logger_ui.info(f"Backing up {kneeboard_name} to {kneeboard_name}.bkp...")
                        shutil.copyfile(kneeboard_name, kneeboard_name + ".bkp")
                    if copy_to_kto:
                        if os.path.isfile(kto_kneeboard_name):
                            logger_ui.info(f"Backing up {kto_kneeboard_name} to {kto_kneeboard_name}.bkp...")
                            shutil.copyfile(kto_kneeboard_name, kto_kneeboard_name + ".bkp")
                    im1 = Image.open(os.path.join(tmp_dir, pages_conv[i])).resize((1024, 2048))
                    im_joined = Image.new("RGBA", (2048, 2048), 'white')
                    im_joined.paste(im1, (im1.size[0], 0))
                    im_joined.save(kneeboard_name)
                    if copy_to_kto:
                        im_joined.save(kto_kneeboard_name)
                    im1.close()
                    im_joined.close()
                else:
                    logger_ui.info("Too many pages, stopping.")
                    break


def _render_export_pages(export_pages, tmp_dir):
    pages_conv = []
    for i, page_ref in enumerate(export_pages):
        out_name = f"page_{i:02d}.png"
        out_path = os.path.join(tmp_dir, out_name)
        if page_ref.kind == "image":
            logger_ui.info(f"Processing an image file: {page_ref.path.name}")
            with Image.open(page_ref.path) as source_img:
                img = source_img.resize((1024, 2048))
                img.save(out_path)
                img.close()
        else:
            page_number = 1 if page_ref.page_index is None else page_ref.page_index + 1
            logger_ui.info(f"Processing PDF page: {page_ref.path.name} page {page_number}")
            with pymupdf.open(page_ref.path) as doc:
                if page_ref.page_index is None or page_ref.page_index >= len(doc):
                    logger_ui.warning(f"Kneeboard order: skipped missing PDF page {page_ref.id}.")
                    continue
                pix = doc[page_ref.page_index].get_pixmap(dpi=150)
                pix.save(out_path)
        pages_conv.append(out_name)
    return pages_conv
