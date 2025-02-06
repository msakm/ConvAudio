#!/usr/bin/env python3

import sys, os
#import pathlib
import time
import subprocess
from multiprocessing import cpu_count
from threading  import Thread
from queue import Queue, Empty

from curses import wrapper
import curses
from curses.textpad import Textbox, rectangle

# ------------------
#      config
# ------------------
# encoders: (mp3, libmp3lame, vorbis, libvorbis, opus, libopus, aac, flac, pcm_s16le)
acodec = 'libmp3lame'
out_ext = 'mp3'
#acodec = 'libopus'
#out_ext = 'opus'

# bitrate (i.e. 64k, 80k, 96k, 128k, 160k, 192k, 256k, 320k)
out_bitrate = '160k'

# sample rate (empty = no change)
out_rate = ''
#out_rate = '44100' # 48000

# output channels (empty = no change)
out_channels = ''

# skip if the output file already exists
out_overwrite = '-n'    # '-n' to skip

# output directory
out_dir = '_converted_'
# ------------------

num_cpus = cpu_count() 
filelist = list()       # list of files to convert
convertedlist = list()  # list of converted files (completed)
proc_list = list()
curses_ui = True        # use curses UI

class FFProcinfo:
    def __init__(self):
        self.time = 0
        self.duration = 0
        self.speed = 0
        self.progress = 0
        self.filename = ''
        self.outfilename = ''
        self.cmd = []
        self.qout = Queue()
        self.proc = None
        self.thread = None

    def ff_out_parser_thr(self):
        out = self.proc.stdout
        for line in iter(out.readline, b''):
            if len(line) > 1:
                self.qout.put(line)
        #out.close()
    
    def initialize(self, in_fname: str):
        fpath, fname = os.path.split(in_fname)
        bname, ext = splitextension(fname)
        ofname = bname + '.' + out_ext
        
        # Python ≥ 3.5
        #from pathlib import Path
        #Path("/my/directory").mkdir(parents=True, exist_ok=True)
        ofpath = out_dir
        if len(fpath) > 1:
            ofpath = fpath + '/' + out_dir
        if not os.path.exists(ofpath):
            os.makedirs(ofpath)
        out_fname = ofpath + '/' + ofname

        if in_fname == out_fname:
            out_fname += '.' + out_ext  # add extension if output filename is the same as input
        
        self.filename = in_fname
        self.outfilename = out_fname
        self.progress = 0
        self.speed = 0
        self.duration = 0
        self.time = 0
        self.cmd = ['ffmpeg', out_overwrite,'-i', in_fname, '-vn', '-c:a', acodec, '-b:a', out_bitrate]
        if len(out_rate) > 0:
            self.cmd += ['-ar', out_rate]
        if len(out_channels) > 0:
            self.cmd += ['-ac', out_channels]
        self.cmd += [out_fname]
        #print(ffinfo.cmd)
        
    def start(self):
        self.proc = subprocess.Popen(self.cmd, shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            universal_newlines=True)
        self.thread = Thread(target = self.ff_out_parser_thr)
        self.thread.daemon = True     # thread dies with the program
        self.thread.start()


def display_progress(scr, idx, progress, finfo):
    #curses.LINES
    #curses.COLS
    maxy, maxx = scr.getmaxyx()
    if idx < 0 | idx > 16:
        return
    scr.move(maxy - idx - 2, 1)

    if progress < 0: 
        progress = 0
    prog = progress / 10
    #curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_WHITE)
    #curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLACK)
    scr.addch(curses.ACS_VLINE)
    for i in range(10):
        if i <= prog:
            scr.addch(curses.ACS_BOARD, curses.color_pair(2) | curses.A_BOLD)
        else:
            scr.addch(curses.ACS_BOARD, curses.color_pair(3))
    
    #stdscr.addch(curses.ACS_CKBOARD, curses.color_pair(2)  | curses.A_BOLD)
    progstr = '{:>3}%'.format(int(progress))
    scr.addstr(progstr)
    scr.addch(curses.ACS_VLINE)
    scr.addch(' ')
    scr.addstr(finfo)

def update_interface(stdscr):
    stdscr.clear()

    stat_lines = 1
    nprocs = num_cpus
    cw_lines = nprocs
    if cw_lines > 16:
        cw_lines = 16
    cw_y = curses.LINES - cw_lines - stat_lines - 2

    # conversion window
    #win = curses.newwin(height, width, begin_y, begin_x)
    conv_win = curses.newwin(cw_lines + 2, curses.COLS, cw_y, 0)
    conv_win.box()

    # completed list window
    compl_lines = cw_y - 2
    compl_win = curses.newwin(cw_y, curses.COLS, 0, 0)
    compl_win.box()
    #window.subwin(begin_y, begin_x)
    #window.subwin(nlines, ncols, begin_y, begin_x)
    scr = compl_win.subwin(1, 1)
    
    compl_lst = convertedlist[-compl_lines:]
    for i, fname in enumerate(compl_lst):
        line = compl_lines - len(compl_lst) + i
        scr.addstr(line, 0, fname)
    
    # Create a custom color set that you might re-use frequently
    # Assign it a number (1-255), a foreground, and background color.
    curses.init_pair(1, curses.COLOR_RED, curses.COLOR_WHITE)
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_WHITE)
    curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLACK)

    for i, ffinfo in enumerate(proc_list):
        display_progress(conv_win, i, ffinfo.progress, ffinfo.filename)
    
    # status info
    num_compl = len(convertedlist)
    num_files = len(convertedlist) + len(filelist) + len(proc_list)
    statstr = 'Converted: {} of {}    Processes: {} / {}'.format(num_compl, num_files, len(proc_list), num_cpus)
    stdscr.addstr(curses.LINES-1, 0, statstr)

    curses.curs_set(0)  # 1 to enable
    stdscr.refresh()
    compl_win.refresh() # refresh completed window
    conv_win.refresh()  # refresh conversion window


# split filename to basename and extension
def splitextension(fname):
    splext = os.path.splitext(fname)
    bname = splext[0]
    ext = splext[1]
    return bname, ext

# parse ffmpeg output
def parse_line(linestr, ffinfo: FFProcinfo):
    if len(linestr) < 5:
        return
    if 'time=' in linestr:
        #size=    3428kB time=00:04:14.63 bitrate= 110.3kbits/s speed=78.1x
        #frame=305055 fps=391 q=34.0 Lsize=  787826kB time=03:03:46.50 bitrate= 585.3kbits/s speed=14.1x
        sstart = linestr.find('time=') + 5
        send = linestr.find(' ', sstart)
        tstr = ''
        ffinfo.time = 0
        if send > sstart:
            tstr = linestr[sstart:send]
        if len(tstr) > 6:
            strlst = tstr.split(':')
            if len(strlst) > 2:
                ffinfo.time = int(strlst[0]) * 3600 + int(strlst[1]) * 60 + float(strlst[2])
        # speed
        sstart = linestr.find('speed=') + 6
        send = linestr.find('x', sstart)
        speedstr = ''
        ffinfo.speed = 0
        if send > sstart:
            speedstr = linestr[sstart:send]
            if len(speedstr) >= 1:
                ffinfo.speed = float(speedstr)
        ffinfo.progress = 0
        if ffinfo.duration > 0:
            ffinfo.progress = 100 * (ffinfo.time / ffinfo.duration)
        #print('Time: ', tstr, '=', ffinfo.time, 'seconds', ', speed =', ffinfo.speed, 'progress (%) =', int(progress),
        #    '  ', ffinfo.filename)
    if 'Duration:' in linestr:
        # example duration line:
        #  Duration: 03:03:46.53, start: 0.000000, bitrate: 4753 kb/s
        durstr = ''
        ffinfo.duration = 0
        sstart = linestr.find('Duration') + 10
        send = linestr.find(',', sstart)
        if send > sstart:
            durstr = linestr[sstart:send]
        if len(durstr) > 6:
            strlst = durstr.split(':')
            if len(strlst) > 2:
                ffinfo.duration = int(strlst[0]) * 3600 + int(strlst[1]) * 60 + float(strlst[2])
        #print('Duration: ', durstr, '=', ffinfo.duration, 'seconds', '  ', ffinfo.filename)
        ffinfo.duration = ffinfo.duration

def ff_out_parser_thr(ffinfo: FFProcinfo):
    out = ffinfo.proc.stdout
    for line in iter(out.readline, b''):
        if len(line) > 1:
            ffinfo.qout.put(line)

# start ffmpeg conversion process for one file
def convert(in_fname: str) -> FFProcinfo:
    ffinfo = FFProcinfo()
    ffinfo.initialize(in_fname)
    ffinfo.start()
    return ffinfo

# convert all files from filelist
def convert_all(scr = None):
    global filelist
    global convertedlist
    global proc_list
    numfiles = len(filelist)
    currentidx = 0
    proc_max = num_cpus
    done = False
    while not done:
        # clear finished processes
        finishedprocs = list()
        for ffproc in proc_list:
            if ffproc.proc.poll() != None:  # process finished
                convertedlist.append(ffproc.filename)
                if scr == None: print('Finished: ', ffproc.filename)
                finishedprocs.append(ffproc)
            while True:
                # read line without blocking
                try:  line = ffproc.qout.get_nowait()     # or procq.get(timeout=.1)
                except Empty: # no output
                    break
                else:       # got line
                    line = line.strip()
                    if len(line) < 3:
                        break
                    parse_line(line.strip(), ffproc)
        # remove finished procs from the list
        for ffproc in finishedprocs:
            proc_list.remove(ffproc)
        
        # start new processes
        while len(proc_list) < proc_max:
            if len(filelist) > 0:
                infname = filelist.pop(0)
                procinf = convert(infname)
                if procinf == None:
                    continue    # process not created
                proc_list.append(procinf)
                currentidx += 1
                outstr = "[{:>3}/{:>3}] {}".format(currentidx, numfiles, procinf.filename)
                if scr == None: print(outstr)
            else:   # no more input files
                break

        # update interface
        if scr != None:
            update_interface(scr)
        # conversion finished and no more input files
        if len(proc_list) < 1 and len(filelist) < 1:
            done = True
        time.sleep(0.5)
    if scr != None:  # don't close immediately
        time.sleep(1)

# convert files passed as args
def process_args():
    global filelist
    fnames = []
    for i, arg in enumerate(sys.argv):
        #print(f"Argument {i:>6}: {arg}")
        if i > 0:
            fnames.append(arg)
    for i, f in enumerate(fnames):
        #print(f"FILE {i+1} of {len(fnames)}: {f}")
        filelist.append(f)
    if curses_ui:   # use curses UI
        curses.wrapper(convert_all)
    else:           # without curses UI
        convert_all()

# convert all files in current dir
def process_all():
    global filelist
    cpath = os.path.abspath(os.getcwd())
    lstfiles = os.listdir(cpath)
    fnames = []
    # TODO: add only files supported by ffmpeg
    for f in lstfiles:
        if(os.path.isfile(f)):
            fnames.append(f)    # add file to the conversion list
    for i, f in enumerate(fnames):
        #print(f"FILE {i+1} of {len(fnames)}: {f}")
        filelist.append(f)
    if curses_ui:   # use curses UI
        curses.wrapper(convert_all)
    else:           # without curses UI
        convert_all()

def main():
    print('CPU count: %d' % (num_cpus))
    if len(sys.argv) > 1:
        process_args()  # convert files passed as args
    else:
        process_all()   # convert all files

if __name__ == "__main__":
    main()
