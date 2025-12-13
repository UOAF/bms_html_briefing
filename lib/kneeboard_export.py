import os, logging, tempfile, shutil

from PIL import Image
import pymupdf

logger = logging.getLogger('html_brief_log')
logger_ui = logging.getLogger('ui_logger')

def export_kneeboards(conf, bms_conf):
    copy_to_kto = (bms_conf.theater_config[bms_conf.theater]['copy_to_kto'] == 'True')
    airframe = conf['bms']['default_airframe']
    src = conf['system']['pdf_output_dir']
    output = bms_conf.theater_config[bms_conf.theater]['target_folder']
    file_list = [f for f in os.listdir(src) if os.path.isfile(os.path.join(src, f))]
    tmp_dir = tempfile.mkdtemp()

    for i,f in enumerate(file_list):
        fname, fext = os.path.splitext(f)
        if fext.lower().strip('.') == "pdf":
            logger_ui.info(f"Processing a pdf file: {f}")
            doc = pymupdf.open(os.path.join(src, f))
            for j, page in enumerate(doc):
                pix = page.get_pixmap(dpi = 150)  # render page to an image
                pix.save(os.path.join(tmp_dir, "page_" + str(i) + f"_conv_{j}.png"))
            doc.close()

        if fext.lower().strip('.') in ['png', 'jpg']:
            logger_ui.info(f"Processing a {fext.lower()} file: {f}")
            img = Image.open(os.path.join(src, f)).resize((1024,2048))
            img.save(os.path.join(tmp_dir, "page_" + str(i) + f"_conv_{i}.png"))
            img.close()


    pages_conv = []

    pages_conv += [f for f in os.listdir(tmp_dir)]
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

    for f in pages_conv:
        os.remove(os.path.join(tmp_dir, f))
    os.rmdir(tmp_dir)
